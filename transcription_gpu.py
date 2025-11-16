import os; import sys; import time
import logging; import warnings; import shutil
import contextlib; import argparse
import subprocess; import json; import math
import whisperx; import torch; import re
# from pydub import AudioSegment
from pathlib import Path
from whisperx.asr import FasterWhisperPipeline
from pandas import DataFrame
from dataclasses import dataclass
from typing import Optional, List, Any, Iterator, Iterable, NamedTuple, Callable, Mapping, TypedDict, Union, Pattern, Tuple
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
    output of transcription or alignment, no speaker
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
    text from segment + label from SpeakerSegment with adjusted intervals from the first and last word
    """
    start: float
    end: float
    speaker: str
    text: str

# external api views returned by whisperx
class SegmentDict(TypedDict):
    """
    raw segment from transcription or alignment
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

class DiarizationSegmentDict(TypedDict, total=False):
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

# diarization output type used throughout
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
    redirects stdout and stderr to /dev/null until the context exits, unless VERBOSE
    """
    if VERBOSE: yield; return
    with open(os.devnull, "w") as devnull, contextlib.redirect_stdout(devnull), contextlib.redirect_stderr(devnull): yield

def format_timestamp(total_seconds: float) -> str:
    """
    converts a timestamp in seconds to hh:mm:ss (like 3661.3 to 01:01:01)
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
        ffmpeg_proc = subprocess.run(ffmpeg_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if ffmpeg_proc.returncode != 0: raise RuntimeError(ffmpeg_proc.stderr.decode(errors="ignore"))
        if VERBOSE: print(f"{input_path} converted to {wav_output_path}")
        return wav_output_path
    except Exception as e:
        raise TranscriptionError(f"file conversion failed: {e}") from e

def transcribe_audio(audio_path: Path, model: FasterWhisperPipeline) -> TranscriptionResult:
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
    aligns raw whisperx segments with the audio via the cached whisperx alignment model
    takes the segment list from a TranscriptionResult and returns an AlignmentResult 
        its "segments" list preserves the original segment-level fields and adds word-level timing information in a "words" field
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

# diarization tuple yielded by itertracks() from pyannote # https://pyannote.github.io/pyannote-core/reference.html#pyannote.core.Annotation.itertracks
class Track(NamedTuple):
    time_span: Any
    track_id: Any
    speaker_label: Any

# diarization tuple yielded by iterrows() from pandas # https://pandas.pydata.org/docs/reference/api/pandas.DataFrame.iterrows.html
class Row(NamedTuple):
    index: Any
    values: Mapping[str, Any]

def _normalize_diarization_turns(diarization_result: DiarizationResult) -> List[SpeakerSegment]:
    """
    normalises diarization outputs into a sorted list of speaker turns

    steps:
        1. extracts all turns as (start, end, label)
        2. drops entries with missing or infinite times and entries with non-positive duration
        3. resets negative start times to 0.0 to avoid negative intervals
        4. sorts the cleaned turns by (start, end)

    returns a normalized list of SpeakerSegment
    """
    speaker_segments: List[SpeakerSegment] = []
    if diarization_result is None: return speaker_segments

    # iterator over tracks is prefered but both are probed
    iterator_over_tracks: Optional[Callable[..., Iterable[Track]]] = getattr(diarization_result, "itertracks", None)
    iterator_over_rows: Optional[Callable[..., Iterable[Row]]] = getattr(diarization_result, "iterrows", None)

    # primary path; pyannote style object with itertracks
    if callable(iterator_over_tracks):
        tracks: Iterable[Track] = iterator_over_tracks(yield_label=True)
        for time_span, _, speaker_label in tracks:
            start_value = getattr(time_span, "start", None)
            end_value = getattr(time_span, "end", None)
            if start_value is None or end_value is None: continue

            speaker_segments.append(SpeakerSegment(start=float(start_value), end=float(end_value), label=str(speaker_label)))

    # fallback; dataframe like object exposing iterrows
    elif callable(iterator_over_rows):
        rows: Iterable[Tuple[Any, Mapping[str, Any]]] = iterator_over_rows()
        for _, row in rows:
            start_value = row.get("start")
            end_value = row.get("end")
            if start_value is None or end_value is None: continue

            label_value = row.get("speaker", row.get("label", "UNKNOWN"))
            speaker_segments.append(SpeakerSegment(start=float(start_value), end=float(end_value), label=str(label_value)))

    # fallback; plain dictionary with a "segments" list
    elif isinstance(diarization_result, dict) and "segments" in diarization_result:
        for row_values in diarization_result["segments"]:
            start_value = row_values.get("start")
            end_value = row_values.get("end")
            if start_value is None or end_value is None: continue

            label_value = row_values.get("speaker") or row_values.get("label") or "UNKNOWN"
            speaker_segments.append(SpeakerSegment(start=float(start_value), end=float(end_value), label=str(label_value)))

    cleaned_segments: List[SpeakerSegment] = []
    for speaker_span in speaker_segments:
        start_seconds = float(speaker_span.start)
        end_seconds = float(speaker_span.end)
        if not (math.isfinite(start_seconds) and math.isfinite(end_seconds)): continue
        if end_seconds <= start_seconds: continue
        if start_seconds < 0.0: start_seconds = 0.0
        cleaned_segments.append(SpeakerSegment(start=start_seconds, end=end_seconds, label=speaker_span.label))

    cleaned_segments.sort(key=lambda segment: (segment.start, segment.end))
    return cleaned_segments


def postprocess_segments(alignment_result: AlignmentResult, diarization_result: DiarizationResult, speaker_gap_threshold: float = 0.8) -> List[Utterance]:
    """
    merges word-level speaker labels into utterances using diarization turns as time boundaries

    params:
    alignment_result comes from whisperx.assign_word_speakers
    diarization_result is a pyannote-style object, DataFrame, or dict
    speaker_gap_threshold is the maximum permitted silence between consecutive words from the same speaker

    steps:
        1. normalises diarization_result into a sorted list of speaker turns
        2. for each aligned segment, calculates cutpoints at turn boundaries inside the segment and splits the segment into subintervals
        3. for each subinterval, finds a default speaker label from the turn that covers the subinterval start, if any
        4. within each subinterval
            assigns each word a label: the per-word "speaker" if present, otherwise the subinterval default label
            groups consecutive words that share the same label and are separated by at most speaker_gap_threshold
        5. joins word strings and avoids unnecessary whitespace

    returns chronologically sorted utterances
    """
    segments = alignment_result.get("segments")
    if not isinstance(segments, list): raise TranscriptionError("alignment_result must contain a segments list")

    utterances: List[Utterance] = []
    leading_punctuation_regex: Pattern[str] = re.compile(r"^[\.\,\!\?\;\:\%\)\]\}]")
    epsilon: float = 0.001

    def _merge_text(previous_text: str, next_text: str) -> str:
        previous_text = (previous_text or "").rstrip()
        next_text = (next_text or "").lstrip()
        if not previous_text: return next_text # the merged result is just the new segment text
        if not next_text: return previous_text # nothing to merge
        last_char: str = previous_text[-1]
        if last_char in "-([{\"'": return previous_text + next_text
        if leading_punctuation_regex.match(next_text): return previous_text + next_text
        return previous_text + " " + next_text

    turns: List[SpeakerSegment] = _normalize_diarization_turns(diarization_result) # sorted turn list
    turn_index: int = 0 # faux pointer into turns
    n_turns: int = len(turns) # cached length for bounds checks

    for segment in segments:
        # pull per-word data and keep only well-formed word entries
        words: List[Mapping[str, Any]] = segment.get("words") or []
        words = [word for word in words if isinstance(word.get("start"), (int, float)) and isinstance(word.get("end"), (int, float)) and isinstance(word.get("word"), str)]
        if not words:
            segment_text: str = segment.get("text")
            seg_start_raw: float = segment.get("start")
            seg_end_raw: float = segment.get("end")
            if (isinstance(segment_text, str) and isinstance(seg_start_raw, (int, float)) and isinstance(seg_end_raw, (int, float))
                and math.isfinite(float(seg_start_raw)) and math.isfinite(float(seg_end_raw)) and float(seg_end_raw) > float(seg_start_raw)):
                seg_start: float = max(0.0, float(seg_start_raw))
                seg_end: float = float(seg_end_raw)
                label_durations: dict[str, float] = {}
                for turn in turns:
                    if turn.end <= seg_start: continue
                    if turn.start >= seg_end: break

                    overlap_start: float = max(seg_start, turn.start)
                    overlap_end: float = min(seg_end, turn.end)
                    if overlap_end <= overlap_start: continue
                    duration: float = overlap_end - overlap_start
                    label_durations[turn.label] = label_durations.get(turn.label, 0.0) + duration

                if label_durations: speaker_label = max(label_durations.items(), key=lambda value: value[1])[0]
                else: speaker_label = "UNKNOWN"
                utterances.append( Utterance( start=seg_start, end=seg_end, speaker=speaker_label, text=segment_text.strip()))
            continue

        seg_start: float = float(words[0]["start"])
        seg_end: float = float(words[-1]["end"])

        while turn_index < n_turns and turns[turn_index].end <= seg_start: turn_index += 1 # advance to first possibly overlapping turn

        cutpoints: List[float] = [seg_start, seg_end] # start with segment bounds
        scan_index: int = turn_index # scan turns that intersect the segment
        while scan_index < n_turns and turns[scan_index].start < seg_end:
            start: float = turns[scan_index].start
            end: float = turns[scan_index].end
            # determine where to split: at turn start or end
            if seg_start < start < seg_end: cutpoints.append(start)
            if seg_start < end < seg_end: cutpoints.append(end)
            if start >= seg_end: break
            scan_index += 1
        cutpoints = sorted(set(cutpoints)) 

        word_index: int = 0 # faux pointer again but for words
        for i in range(len(cutpoints) - 1): # iterate each subinterval produced by cutpoints
            start: float = cutpoints[i]
            end = cutpoints[i + 1]
            if end - start <= epsilon: continue

            # collect words inside the subinterval
            interval_words: List[Mapping[str, Any]] = []
            while word_index < len(words) and float(words[word_index]["end"]) <= start + epsilon: word_index += 1
            while word_index < len(words) and float(words[word_index]["start"]) <= end - epsilon: interval_words.append(words[word_index]); word_index += 1
            if not interval_words: continue

            current_label: Optional[str] = None
            current_words: List[Mapping[str, Any]] = []
            for word in interval_words:
                word_label: str = str(word.get("speaker") or "UNKNOWN")
                if current_label is None: current_label = word_label; current_words = [word]; continue
                gap_seconds: float = float(word["start"]) - float(current_words[-1]["end"])
                if word_label == current_label and gap_seconds <= speaker_gap_threshold: current_words.append(word)
                else: # flush previous run as an utterance
                    text: str = ""
                    for word_entry in current_words: text = _merge_text(text, str(word_entry["word"]))
                    utterances.append(Utterance(start=float(current_words[0]["start"]), end=float(current_words[-1]["end"]), speaker=str(current_label), text=text.strip()))
                    current_label = word_label; current_words = [word]

            if current_words: # flush anything remaining
                text: str = ""
                for word_entry in current_words: text = _merge_text(text, str(word_entry["word"]))
                utterances.append(Utterance(start=float(current_words[0]["start"]), end=float(current_words[-1]["end"]), speaker=str(current_label), text=text.strip()))

    utterances.sort(key=lambda utterance: (utterance.start, utterance.end))
    merged_utterances: List[Utterance] = []
    for utterance in utterances:
        if not merged_utterances: merged_utterances.append(utterance); continue
        last_utterance = merged_utterances[-1]
        gap = max(0.0, float(utterance.start) - float(last_utterance.end))
        if utterance.speaker == last_utterance.speaker and gap <= speaker_gap_threshold:
            merged_utterances[-1] = Utterance(
                start=last_utterance.start,
                end=max(last_utterance.end, utterance.end),
                speaker=last_utterance.speaker,
                text=_merge_text(last_utterance.text, utterance.text),
            )
        else: merged_utterances.append(utterance)

    return merged_utterances

def transcribe_with_diarization(audio_path: Path, model: FasterWhisperPipeline, output_path: Path, output_format: str) -> None:
    """
    this basically just calls all the functions above to make the full transcription pipeline and write the result to disk
    also computes and prints the time the script took processing the file, i was using that to track how well the script was optimised
    """
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
        alignment_result = whisperx.assign_word_speakers(diarization_result, alignment_result)
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




def main() -> int:
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
    input_path: Path = Path(args.input_file)
    if not input_path.is_file():
        print(f"{input_path} does not exist")
        sys.exit(1)

    # decide whether conversion to .wav is necessary
    extension:str = input_path.suffix.lower()
    wav_converted:bool = False
    wav_path: Path = input_path
    try:
        if extension == ".wav": wav_path = input_path;  wav_converted = False
        else: wav_path = convert_to_wav(input_path);    wav_converted = True

        def _overwrite(output_path: Path, overwrite_flag: bool) -> Path:
            """
            decides the filepath to use for the output file

            if the overwrite flag is false:
                if output path does not yet exist returns output path
                if output path already exists appends or increments a counter until a non existing path is found and returns that path
            otherwise returns the given output path
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

        if not torch.cuda.is_available():
            raise TranscriptionError("cuda is unavailable. https://developer.nvidia.com/cuda-downloads")

        # load whisperx model
        try:
            with _suppress_everything(): whisper_model = whisperx.load_model(args.model, DEVICE, compute_type="float16")
        except RuntimeError as e:
            message = str(e).lower()
            if "float16" in message or "half" in message or "fp16" in message:
                if VERBOSE: print("float16 is not supported on this device, falling back to float32")
                with _suppress_everything(): whisper_model = whisperx.load_model(args.model, DEVICE, compute_type="float32")
            else: raise TranscriptionError(f"model '{args.model}' failed to load: {e}") from e
        except Exception as e: raise TranscriptionError(f"model '{args.model}' failed to load: {e}") from e

        # do the thing!
        transcribe_with_diarization(wav_path, whisper_model, output_path, args.out_format)
        return 0
    except TranscriptionError as e:
        if VERBOSE: raise
        print(str(e), file=sys.stderr)
        return 1
    finally:
        if "wav_converted" in locals() and wav_converted and not args.keep_wav and "wav_path" in locals() and wav_path.exists():
            try: wav_path.unlink()
            except Exception as e: print(f"could not delete wav: {e}", file=sys.stderr)
    
if __name__ == "__main__": sys.exit(main())