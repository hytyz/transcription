import os; import sys; import time
import logging; import warnings; import shutil
import contextlib; import argparse
import subprocess; import json
import whisperx; import torch; import re
# from pydub import AudioSegment
from pathlib import Path
from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional, List, Any, Iterator, Iterable, NamedTuple, Callable, Mapping, TypedDict, Union
from pyannote.core import Annotation
from lightning.pytorch.utilities import disable_possible_user_warnings

DEVICE: str = "cuda"            # required for diarization on gpu
VERBOSE: bool = False           # controls logging and output suppression
_ALIGN_MODEL = None             # cached whisperx alignment model instance, created on first use by _get_align_model
_ALIGN_METADATA = None          # cached metadata of the alignment model
_DIARIZATION_PIPELINE = None    # cached diarization pipeline instance, created on first use by _get_diarization_pipeline

# for loading the pyannote diarization model
token: Optional[str] = os.environ.get("HF_TOKEN")
if token is None or token.strip() == "":
    print("missing huggingface token. `set/export HF_TOKEN=token`")
    sys.exit(1)
HF_TOKEN: str = token

# internal objects
@dataclass
class Segment:
    """
    output of transcription and alignment, no speaker
    """
    start: float
    end: float
    text: str

@dataclass
class SpeakerSegment:
    """
    output of diarization, no text
    """
    start: float
    end: float
    label: str

@dataclass
class Utterance:
    """
    text from segment + label from SpeakerSegment with adjusted intervals from both
    """
    start: float
    end: float
    speaker: str
    text: str

# external api views returned by whisperx
class SegmentDict(TypedDict):
    """
    raw segment from transcription or alignment without speaker information
    """
    start: float
    end: float
    text: str

class TranscriptionResult(TypedDict):
    """
    output of the transcription step

    segments is the list of raw segments produced by the whisperx model before alignment
    """
    segments: List[SegmentDict]

class AlignmentResult(TypedDict):
    """
    output of the alignment step
    segments is the list of segments from TranscriptionResult
    """
    segments: List[SegmentDict]

class DiarizationSegmentDict(TypedDict):
    """
    a single diarization segment
    """
    start: float
    end: float
    speaker: str
    label: str

class DiarizationDict(TypedDict):
    """
    diarization output that exposes a segments collection
    """
    segments: List[DiarizationSegmentDict]

if TYPE_CHECKING: from pandas import DataFrame
DiarizationResult = Union[Annotation, DataFrame, DiarizationDict]

class TranscriptionError(Exception): pass

def _get_align_model():
    """
    loads and caches the whisperx alignment model and metadata
    subsequent calls reuse the cached objects instead of reloading the model
    """
    global _ALIGN_MODEL, _ALIGN_METADATA
    if _ALIGN_MODEL is None or _ALIGN_METADATA is None: _ALIGN_MODEL, _ALIGN_METADATA = whisperx.load_align_model(language_code="en", device=DEVICE)
    return _ALIGN_MODEL, _ALIGN_METADATA

def _get_diarization_pipeline():
    
    """
    loads and caches the pyannote diarization pipeline used by whisperx
    subsequent calls reuse the cached pipeline instance
    """
    global _DIARIZATION_PIPELINE
    if _DIARIZATION_PIPELINE is None:
        _DIARIZATION_PIPELINE = whisperx.diarize.DiarizationPipeline(model_name="pyannote/speaker-diarization@2.1", use_auth_token=HF_TOKEN, device=DEVICE)
        try: _DIARIZATION_PIPELINE.set_params({"clustering": {"threshold": 0.70}})
        except Exception as e: 
            if VERBOSE: print(f"could not set diarization clustering threshold: {e}")
    return _DIARIZATION_PIPELINE

def _configure_verbosity(verbose: bool) -> None:
    """
    sets the global VERBOSE flag and configures warnings and logging levels
    """
    global VERBOSE
    VERBOSE = verbose
    if VERBOSE:
        warnings.resetwarnings(); warnings.filterwarnings("default")
        logging.basicConfig(level=logging.INFO)
        logging.getLogger("pyannote").setLevel(logging.INFO)
        logging.getLogger("pytorch_lightning").setLevel(logging.INFO)
        logging.getLogger("whisperx").setLevel(logging.INFO)
    else:
        disable_possible_user_warnings(); warnings.filterwarnings("ignore")
        logging.basicConfig(level=logging.ERROR)
        logging.getLogger("pyannote").setLevel(logging.ERROR)
        logging.getLogger("pytorch_lightning").setLevel(logging.ERROR)
        logging.getLogger("whisperx").setLevel(logging.ERROR)

@contextlib.contextmanager
def _suppress_everything() -> Iterator[None]:
    """
    redirects stdout and stderr to /dev/null until the context exits, unless verbose
    """
    if VERBOSE: yield; return
    with open(os.devnull, "w") as devnull, contextlib.redirect_stdout(devnull), contextlib.redirect_stderr(devnull): yield

def format_timestamp(total_seconds: float) -> str:
    """
    converts a timestamp in seconds to hh:mm:ss (3661.3 to 01:01:01). fractional seconds are discarded
    """
    hours: int = int(total_seconds // 3600)
    minutes: int = int((total_seconds % 3600) // 60)
    seconds: int = int(total_seconds % 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"

def format_duration(seconds: float) -> str:
    """
    converts a duration in seconds to a readable string
    this is for reporting total processing time to the console
    """
    def _plural(unit: str, value: int) -> str: return f"{value} {unit}" + ("s" if value != 1 else "")
    if seconds < 60: return f"{seconds:.1f} {"second" if int(round(seconds)) == 1 else "seconds"}"
    minutes, remaining_seconds = divmod(int(seconds), 60)
    if minutes < 60: return f"{_plural('minute', minutes)} and {_plural('second', int(remaining_seconds))}"
    hours, minutes = divmod(minutes, 60)
    return f"{_plural('hour', hours)}, {_plural('minute', minutes)} and {_plural('second', int(remaining_seconds))}"

def convert_to_wav(input_path: Path) -> Path:
    """
    converts an audio file to a 16 kHz, 16.bit pcm wav using ffmpeg
    the output file shares the same base name as the input, but with a .wav extension
    whisperx requires .wav
    """
    if not shutil.which("ffmpeg"): raise TranscriptionError("ffmpeg not found. https://ffmpeg.org/download.html")

    wav_output_path = input_path.with_suffix(".wav")
    if not input_path.is_file(): raise TranscriptionError(f"'{input_path}' not found")

    ffmpeg_cmd = [
        "ffmpeg", "-y",         # overwrites any existing output file
        "-i", str(input_path),  # the file passed in params as source
        # "-ac", "1",
        "-ar", "16000",         # sample rate 16 kHz
        "-sample_fmt", "s16",   # sample format 16-bit signed
        "-c:a", "pcm_s16le",    # pcm_s16le codec
        str(wav_output_path),
    ]

    try:
        with _suppress_everything(): ffmpeg_proc = subprocess.run(ffmpeg_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if ffmpeg_proc.returncode != 0: raise RuntimeError(ffmpeg_proc.stderr.decode(errors="ignore"))
        if VERBOSE: print(f"{input_path} converted to {wav_output_path}") # only informs user of conversion if verbose passed
        return wav_output_path
    except Exception as e: raise TranscriptionError(f"file conversion failed: {e}") from e

def transcribe_audio(audio_path: Path, model) -> TranscriptionResult:
    """
    performs transcription on the given audio using a preloaded whisperx model
    uses torch.inference_mode() to disable gradient tracking for speed and lower memory usage

    returns a dictionary with the raw transcription output: segments is a list of segments, each including
    1. start and end timestamps, and 2. text string
    """     
    with _suppress_everything():
        with torch.inference_mode(): result: TranscriptionResult = model.transcribe(str(audio_path), language="en", task="transcribe")
    return result

def align_transcription(segments: List[SegmentDict], audio_path: Path) -> AlignmentResult:
    """
    aligns raw whisperx segments with the audio at a finer time resolution via the cached whisperx alignment model
    returns an AlignmentResult with segments list that contains the input segments with better start and end timestamps
    """
    with _suppress_everything():
        align_model, align_metadata = _get_align_model()
        alignment_result: AlignmentResult = whisperx.align(segments, align_model, align_metadata, str(audio_path), DEVICE)
    return alignment_result

def run_diarization(audio_path: Path) -> DiarizationResult:
    """
    runs speaker diarization on an audio file using the cached pipeline through whisperx
    returns an object describing contiguous time spans for each detected speaker
    """
    with _suppress_everything():
        diarization_pipeline = _get_diarization_pipeline()
        diarization_result: DiarizationResult = diarization_pipeline(str(audio_path))
    return diarization_result

# these two are used in _normalize_diarization()
# diarization tuple yielded by itertracks() from pyannote # https://pyannote.github.io/pyannote-core/reference.html#pyannote.core.Annotation.itertracks
class Track(NamedTuple):
    time_span: Any
    track_id: Any
    speaker_label: Any

# diarization tuple yielded by iterrows() from pandas # https://pandas.pydata.org/docs/reference/api/pandas.DataFrame.iterrows.html
class Row(NamedTuple):
    index: Any
    data: Mapping[str, Any]
def postprocess_segments(alignment_result: AlignmentResult, diarization_result: DiarizationResult, speaker_gap_threshold: float = 0.8) -> List[Utterance]:
    """
    combines aligned transcription segments with diarization output into coherent speaker labeled utterances

    params:
    alignment_result is an AlignmentResult from align_transcription() with a segments list
    diarization_result is the diarization output
    speaker_gap_threshold is the maximum gap in seconds between two segments from the same speaker for them to be merged into a single utterance

    steps:
        1. cleans aligned segments:
            reads alignment_result and strips whitespace
            builds Segment objects and sorts them chronologically
        2. normalises diarization:
            converts diarization_result into a list of SpeakerSegment(start, end, label) using itertracks, iterrows, or a "segments" list
            sorts speaker_segments chronologically
        3. assigns speakers:
            if speaker_segments is empty, every interval is labeled UNKNOWN
            otherwise
                assigns the speaker label with maximum temporal overlap
                falls back to the speaker whose span contains the midpoint
                falls back to UNKNOWN
        4. labels segments:
            for each cleaned Segment creates an Utterance(start, end, speaker, text)
            sorts labeled_segments chronologically
        5. merges into utterances:
            iterates over labeled_segments chronologically
            if the current segment has the same speaker as the last utterance and the gap is <= given speaker_gap_threshold, merges:
                updates the text of the last utterance
                extends the end of the last_utterance to the current segment end
            otherwise starts a new Utterance

    returns a list of Utterance objects in chronological order
    """
    # extract aligned segments from the alighnment result
    aligned_segments: List[SegmentDict] = alignment_result["segments"]

    # clean segments
    cleaned_segments: List[Segment] = []
    for segment in aligned_segments:
        text: str = segment["text"].strip()
        if not text: continue # skip if the segment is all whitespace
        start_time: float = float(segment["start"])
        end_time: float = float(segment["end"])
        # only keep segments that have positive duration
        if end_time > start_time: cleaned_segments.append(Segment(start=start_time, end=end_time, text=text))
    if not cleaned_segments: return [] # if there are no valid segments after cleaning
    cleaned_segments.sort(key=lambda segment: (segment.start, segment.end))

    def _normalize_diarization(diarization_result: DiarizationResult) -> List[SpeakerSegment]:
        """
        normalise diarization_result into a list of SpeakerSegments (like {start: float, end: float, label: str})
        """
        speaker_segments: List[SpeakerSegment] = []
        if diarization_result is None: return speaker_segments

        iterator_over_tracks: Optional[Callable[..., Iterable[Track]]] = getattr(diarization_result, "itertracks", None)
        iterator_over_rows: Optional[Callable[..., Iterable[Row]]] = getattr(diarization_result, "iterrows", None)

        # primary path; pyannote style object with itertracks
        if callable(iterator_over_tracks):
            tracks: Iterable[Track] = iterator_over_tracks(yield_label=True)
            for time_span, _, speaker_label in tracks: speaker_segments.append( SpeakerSegment(
                        start=float(time_span.start),
                        end=float(time_span.end),
                        label=str(speaker_label)))
    
        # fallback; dataframe like object exposing iterrows
        elif callable(iterator_over_rows):
            rows: Iterable[Row] = iterator_over_rows()
            for _, row in rows: speaker_segments.append( SpeakerSegment(
                        start=float(row["start"]),
                        end=float(row["end"]),
                        label=str(row.get("speaker", row.get("label", "UNKNOWN")))))
    
        # fallback; plain dictionary with a "segments" list
        elif isinstance(diarization_result, dict) and "segments" in diarization_result:
            for row in diarization_result["segments"]: speaker_segments.append(SpeakerSegment(
                        start=float(row.get("start", 0.0)),
                        end=float(row.get("end", 0.0)),
                        label=str(row.get("speaker") or row.get("label") or "UNKNOWN")))
                
        speaker_segments.sort(key=lambda span: (span.start, span.end))
        return speaker_segments
    
    speaker_segments: List[SpeakerSegment] = _normalize_diarization(diarization_result)

    if not speaker_segments:
        # if diarization produced nothing usable always return unknown
        def _speaker_for_interval(start_time: float, end_time: float) -> str: return "UNKNOWN"
    else:
        # segment_index is a faux pointer that points to the first diarization segment that could possibly overlap the current transcription segment
        segment_index: int = 0
        def _speaker_for_interval(start_time: float, end_time: float) -> str:
            """
            determines the most likely speaker label for a transcription interval

            steps:
            1. overlap based assignment:
                advance segment_index to skip any diarization spans that end at or before start_time
                from segment_index onward, compute overlap with each span whose start is before end_time
                track the label with the max overlap duration; return that label if any positive overlap is found
            2. if no overlap:
                compute the midpoint of the interval
                from segment_index onward, find the first diarization span that contains this midpoint; return that label if span is found
            3. otherwise return "UNKNOWN"
            """
            nonlocal segment_index
            n_of_segments:int = len(speaker_segments)
            # after this loop speaker_segments[segment_index] is the earliest span that could overlap [start_time, end_time)
            while segment_index < n_of_segments and speaker_segments[segment_index].end <= start_time: segment_index += 1

            best_label: Optional[str] = None
            max_overlap_seconds: float = 0.0
            midpoint_second = 0.5 * (start_time + end_time)

            # scan onward from segment_index to find overlapping spans and get the one with maximum overlap
            i:int = segment_index
            midpoint_label: Optional[str] = None
            while i < n_of_segments:
                span = speaker_segments[i]
                if span.start >= end_time: break # once the start of the span is at or after the end time no further overlaps are possible
                overlap_seconds: float = max(0.0, min(end_time, span.end) - max(start_time, span.start),)
                if overlap_seconds > max_overlap_seconds: max_overlap_seconds = overlap_seconds; best_label = span.label # update the best label if computed overlap is strictly larger than any previous
                if span.start <= midpoint_second < span.end and midpoint_label is None: midpoint_label = span.label # fallback if no overlap -- use the midpoint of the interval to look for a containing span
                i += 1

            if best_label is not None and max_overlap_seconds > 0.0:
                return best_label
            if midpoint_label is not None:
                return midpoint_label
            return "UNKNOWN"
        
    # label each segment with a speaker
    labeled_segments: List[Utterance] = []
    for segment in cleaned_segments:
        speaker_label: str = _speaker_for_interval(segment.start, segment.end)
        labeled_segments.append(Utterance(start=segment.start, end=segment.end, speaker=speaker_label, text=segment.text,))
    labeled_segments.sort(key=lambda segment: (segment.start, segment.end))

    def _merge_text(previous_text: str, next_text: str) -> str:
        """
        merges two text fragments into a single string; avoids double spaces, missing spaces between words, and spaces before punctuation
        
        if the previous text ends with whitespace, dash, or an opening punctuation do not add a space
        if the new segment starts with closing or separating punctuation do not add a space
        otherwise add a space
        """
        
        def _needs_space_between(previous_text: str, next_text: str) -> bool:
            """
            decides whether a space should be inserted between two text fragments.
            """
            if not previous_text or not next_text: return False
            if re.compile(r"^[\.\,\!\?\;\:\%\)\]\}]").match(next_text): return False
            last_char = previous_text[-1]
            if last_char.isspace() or last_char in "-([{\"'": return False
            return True

        if not next_text: return previous_text # nothing to merge
        if not previous_text: return (next_text or "").lstrip() # the merged result is just the new segment text

        next_text = next_text.lstrip()
        if _needs_space_between(previous_text, next_text): return previous_text + " " + next_text
        return previous_text + next_text

    # merge consecutive segments from the same speaker into longer utterances
    utterances: List[Utterance] = []
    for segment in cleaned_segments:
        speaker_label = _speaker_for_interval(segment.start, segment.end)
        if (utterances and utterances[-1].speaker == speaker_label and (segment.start - utterances[-1].end) <= speaker_gap_threshold):
            last_utterance: Utterance = utterances[-1]
            last_utterance.text = _merge_text(last_utterance.text, segment.text)
            last_utterance.end = segment.end
        else: utterances.append(Utterance(
            start=segment.start,
            end=segment.end,
            speaker=speaker_label,
            text=segment.text,)) # for better scoping

    return utterances

def transcribe_with_diarization(audio_path: Path, model, output_path: Path, output_format: str) -> None:
    """
    this basically just calls all the functions above to make the full transcription pipeline and write the result to disk
    also computes and prints the time the script took processing the file, i was using that to track how well the script was optimised
    any exception raised in the pipeline steps throws an error and exits the program
    """
    if not torch.cuda.is_available():
        print("cuda is unavailable. https://developer.nvidia.com/cuda-downloads")
        sys.exit(1)

    print(f"\nprocessing: {audio_path}")
    start_time: float = time.perf_counter()

    try:
        print("transcribing")
        transcription_result: TranscriptionResult = transcribe_audio(audio_path, model) # after model ", DEVICE"
        # torch.cuda.empty_cache() # emptying cache avoids ooms at the cost of processing speed

        print("aligning")
        alignment_result: AlignmentResult = align_transcription(transcription_result["segments"], audio_path)
        # torch.cuda.empty_cache()

        print("diarizing")
        diarization_result: DiarizationResult = run_diarization(audio_path)
        # torch.cuda.empty_cache()

        print("post processing")
        utterances = postprocess_segments(alignment_result, diarization_result)

    except Exception as e: raise TranscriptionError(f"transcription with diarization failed: {e}") from e

    end_time: float = time.perf_counter()
    if output_format == "json": file_body = json.dumps([
            {"start": utterance.start, "end": utterance.end, "speaker": utterance.speaker, "text": utterance.text}
            for utterance in utterances
        ], ensure_ascii=False, indent=2)
    else:
        formatted_lines = [
        f"[{format_timestamp(utterance_line.start)}] {utterance_line.speaker}: {utterance_line.text}"
        for utterance_line in utterances
        ]
        file_body = "\n".join(formatted_lines)

    output_path.write_text(file_body, encoding="utf-8")
    print(f"saved to: {output_path}")
    print(f"\ntook {format_duration(end_time-start_time)}")

if __name__ == "__main__":
    # total_start_time: float = time.perf_counter()
    parser = argparse.ArgumentParser()
    parser.add_argument("input_file")
    parser.add_argument("--model", default="medium")                                    # can specify a different whisperx model
    parser.add_argument("-v", "--verbose", action="store_true")                         # enables all logs for debugging
    parser.add_argument("-k", "--keep-wav", action="store_true")                        # doesn't delete intermediate .wav
    parser.add_argument('-o', '--overwrite', action='store_true')                       # overwrites any existing outputs
    parser.add_argument('-f', '--out_format', choices=['txt','json'], default='txt')    # deprecate? idk if i will actually ever need .json outputs
    args = parser.parse_args()

    _configure_verbosity(args.verbose)

    # resolve and validate the input path
    input_path = Path(args.input_file)
    if not input_path.is_file():
        print(f"{input_path} does not exist")
        sys.exit(1)

    # decide whether conversion to .wav is necessary
    extension = input_path.suffix.lower()
    if extension == ".wav": wav_path = input_path;  wav_converted = False
    else: wav_path = convert_to_wav(input_path);    wav_converted = True

    def _overwrite(output_path: Path, overwrite_flag: bool) -> Path:
        """
        decides the filepath to use for the output file

        if overwriting is not permitted:
            if output path does not yet exist return output path
            if output_path already exists recursively add a counter to the output path
        """
        if not output_path.exists() or overwrite_flag: return output_path

        def bump(path: Path) -> Path:
            parts = path.stem.rsplit("_", 1)
            if len(parts) == 2 and parts[1].isdigit():
                base = parts[0]
                number = int(parts[1]) + 1
            else:
                base = path.stem
                number = 1
            while True:
                candidate = path.parent / f"{base}_{number}{path.suffix}"
                if not candidate.exists(): return candidate
                number += 1
        
        return bump(output_path)

    # determine output filename
    ext = ".json" if args.out_format == "json" else ".txt"
    output_path = wav_path.with_suffix(ext)
    output_path = _overwrite(output_path, args.overwrite)

    # load whisperx model
    try:
        with _suppress_everything(): whisper_model = whisperx.load_model(args.model, DEVICE, compute_type="float16")
    except RuntimeError as e:
        message = str(e).lower()
        if "float16" in message or "half" in message or "fp16" in message:
            if VERBOSE: print("float16 is not supported on this device, falling back to float32")
            with _suppress_everything(): whisper_model = whisperx.load_model(args.model, DEVICE, compute_type="float32")
        raise TranscriptionError(f"model '{args.model}' failed to load: {e}") from e
    except Exception as e:
        raise TranscriptionError(f"model '{args.model}' failed to load: {e}") from e

    try:
        with _suppress_everything(): whisper_model = whisperx.load_model(args.model, DEVICE, compute_type="float16")
    except Exception as e: print(f"model '{args.model}' failed to load. {e}"); sys.exit(1)

    # do the thing!
    try: transcribe_with_diarization(wav_path, whisper_model, output_path, args.out_format)
    except TranscriptionError as e: 
        if VERBOSE: raise; print(e)
        sys.exit(1)
    finally: 
        # total_end_time: float = time.perf_counter()
        # print(f"\ntotal {format_duration(total_end_time-total_start_time)}")
        if wav_converted and not args.keep_wav and wav_path.exists(): 
            try: wav_path.unlink() 
            except Exception as e: print(f"could not delete wav. {e}")
