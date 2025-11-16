
import os; import sys; import time
import logging; import warnings; import shutil
import contextlib; import argparse
import subprocess; import json
import whisperx; import torch
# from pydub import AudioSegment
from pathlib import Path
from dataclasses import dataclass
from typing import Optional, List, Dict, Any, Iterator, Iterable, Tuple, Callable, Mapping, cast
from lightning.pytorch.utilities import disable_possible_user_warnings

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

WordDict = Dict[str, Any] # type alias to hold arbitrary metadata for utterances
DEVICE: str = "cuda"
VERBOSE: bool = False

# for loading the pyannote diarization model
RAW_HF_TOKEN: Optional[str] = os.environ.get("HF_TOKEN")
if not RAW_HF_TOKEN:
    print("missing huggingface token. `set/export HF_TOKEN=token`")
    sys.exit(1)
HF_TOKEN: str = RAW_HF_TOKEN

if not torch.cuda.is_available():
    print("cuda is unavailable. https://developer.nvidia.com/cuda-downloads")
    sys.exit(1)

def check_ffmpeg():
    """
    ensures that ffmpeg is available on the path
    only gets called if a non-.wav file is passed for transcription
    """
    if not shutil.which("ffmpeg"):
        print("ffmpeg not found. https://ffmpeg.org/download.html")
        sys.exit(1)

def suppress_logs() -> None:
    """
    disables user warnings from lightning, filters out python warnings, and sets logging levels to error, unless verbose is passed
    """
    if VERBOSE: return
    disable_possible_user_warnings()
    warnings.filterwarnings("ignore")
    logging.getLogger("pyannote").setLevel(logging.ERROR)
    logging.getLogger("pytorch_lightning").setLevel(logging.ERROR)
    logging.getLogger("whisperx").setLevel(logging.ERROR)

@contextlib.contextmanager
def suppress_everything() -> Iterator[None]:
    """
    redirects stdout and stderr to /dev/null until the context exits, unless verbose is passed
    """
    if VERBOSE: yield; return
    with open(os.devnull, "w") as devnull:
        original_stdout = sys.stdout; original_stderr = sys.stderr
        try: sys.stdout = devnull; sys.stderr = devnull; yield
        finally: sys.stdout = original_stdout; sys.stderr = original_stderr

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
    if seconds < 60: return f"{seconds:.1f} second{'s' if int(seconds) != 1 else ''}"
    seconds = int(seconds)
    minutes: int = int(seconds // 60)
    remaining_seconds: float = seconds % 60
    if minutes < 60: return f"{minutes} minute{'s' if minutes != 1 else ''} and {int(remaining_seconds)} seconds"
    hours: int = int(minutes // 60)
    minutes = minutes % 60
    return f"{hours} hour{'s' if hours != 1 else ''}, {minutes} minute{'s' if minutes != 1 else ''} and {int(remaining_seconds)} second{'s' if int(remaining_seconds) != 1 else ''}"

def convert_to_wav(input_path: Path) -> Path:
    """
    converts an audio file to a 16 kHz, 16.bit pcm wav using ffmpeg
    the output file shares the same base name as the input, but with a .wav extension
    whisperx requires .wav
    """
    check_ffmpeg()
    wav_output_path = input_path.with_suffix(".wav")
    if not input_path.is_file():
        print(f"'{input_path}' not found")
        sys.exit(1)
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
        with suppress_everything(): ffmpeg_proc = subprocess.run(ffmpeg_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if ffmpeg_proc.returncode != 0: raise RuntimeError(ffmpeg_proc.stderr.decode(errors="ignore"))
        if VERBOSE: print(f"{input_path} converted to {wav_output_path}") # only informs user of conversion if verbose passed
        return wav_output_path
    except Exception as e:
        print(f"file conversion failed: {e}")
        sys.exit(1)

def transcribe_audio(audio_path: Path, model) -> WordDict: # after model ", device: str"
    """
    performs transcription on the given audio using a preloaded whisperx model
    uses torch.inference_mode() to disable gradient tracking for speed and lower memory usage

    returns a dictionary with the raw transcription output: segments is a list of segments, each including
    1. start and end timestamps, and 2. text string
    """     
    with suppress_everything():
        # whisper_model = whisperx.load_model(model_name, device, compute_type="float16")
        with torch.inference_mode(): result: WordDict = model.transcribe(str(audio_path), language="en", task="transcribe")
    return result

def align_transcription(segments, audio_path: Path) -> WordDict:
    """
    aligns raw whisperx segments with the audio at a finer time resolution via whisperx alignment model
    returns a dictionary with alignment results: ssegments is a list of segments from transcribe_audio() with refined timestamps
    """
    with suppress_everything():
        align_model, align_metadata = whisperx.load_align_model(language_code="en", device=DEVICE)
        alignment_result: WordDict = whisperx.align(segments, align_model, align_metadata, str(audio_path), DEVICE)
    return alignment_result

def run_diarization(audio_path: Path, hf_token: str):
    """
    runs speaker diarization on an audio file using the pyannote pipeline through whisperx
    returns an object describing contiguous time spans for each detected speaker
    """
    with suppress_everything():
        diarization_pipeline = whisperx.diarize.DiarizationPipeline(
            model_name='pyannote/speaker-diarization@2.1', # do NOT change
            use_auth_token=hf_token,
            device=DEVICE
        )
        try: diarization_pipeline.set_params({"clustering": {"threshold": 0.70}}) # lower is more sensitive => more speakers, try adjusting
        except Exception: print("clustering treshold didn't pass"); pass # i'm not sure whether this param is actually supported in the api
        diarization_result = diarization_pipeline(str(audio_path))
    return diarization_result

# these two are used in normalize_diarization()
# diarization tuple yielded by itertracks() from pyannote # https://pyannote.github.io/pyannote-core/reference.html#pyannote.core.Annotation.itertracks
Track = Tuple[Any, Any, Any] # (time_span, track_id, speaker_label) 
# diarization tuple yielded by iterrows() from pandas # https://pandas.pydata.org/docs/reference/api/pandas.DataFrame.iterrows.html
Row = Tuple[Any, Mapping[str, Any]] # (index, row_data)

def postprocess_segments(alignment_result: WordDict, diarization_result, speaker_gap_threshold: float = 0.8) -> List[WordDict]:
    """
    combines aligned transcription segments with diarization output into coherent speaker labeled utterances

    params:
    alignment_result is a dictionary from align_transcription() with a "segments" list
    diarization_result is the diarization output
    speaker_gap_threshold is the maximum gap in seconds between two segments from the same speaker for them to be merged into a single utterance

    steps:
        1. cleans aligned segments:
            reads alignment_result and strip
            builds Segment(start, end, text) objects and sorts chronologically
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

    returns a list of dictionaries, each with keys "start", "end", "speaker", "text", representing speaker labeled utterances in chronological order
    """
    # extract aligned segments from the alighnment result
    aligned_segments: List[WordDict] = alignment_result.get("segments") or []

    # clean segments
    cleaned_segments: List[Segment] = []
    for segment in aligned_segments:
        text: str = (segment.get("text") or "").strip()
        if not text: continue # skip if the segment is all whitespace
        start_time: float = float(segment.get("start", 0.0))
        end_time: float = float(segment.get("end", start_time))
        # only keep segments that have positive duration
        if end_time > start_time: cleaned_segments.append(Segment(start=start_time, end=end_time, text=text))
    if not cleaned_segments: return [] # if there are no valid segments after cleaning
    cleaned_segments.sort(key=lambda segment: (segment.start, segment.end))

    def normalize_diarization(diarization_result) -> List[SpeakerSegment]:
        """
        normalise diarization_result into a list of SpeakerSegments (like {start: float, end: float, label: str})
        """
        speaker_segments: List[SpeakerSegment] = []
        if diarization_result is None: return speaker_segments

        # primary path; pyannote style object with itertracks
        iterator_over_tracks: Optional[Callable[..., Iterable[Track]]] = getattr(diarization_result, "itertracks", None)
        if callable(iterator_over_tracks):
            tracks: Iterable[Track] = iterator_over_tracks(yield_label=True)
            for time_span, _, speaker_label in tracks:
                speaker_segments.append(
                    SpeakerSegment(
                        start=float(time_span.start),
                        end=float(time_span.end),
                        label=str(speaker_label),
                    )
                )
            speaker_segments.sort(key=lambda span: (span.start, span.end))
            return speaker_segments
    
        # fallback; dataframe like object exposing iterrows
        iterator_over_rows: Optional[Callable[..., Iterable[Row]]] = getattr(diarization_result, "iterrows", None)
        if callable(iterator_over_rows):
            rows: Iterable[Row] = iterator_over_rows()
            for _, row in rows:
                speaker_segments.append(
                    SpeakerSegment(
                        start=float(row["start"]),
                        end=float(row["end"]),
                        label=str(row.get("speaker", row.get("label", "UNKNOWN"))),
                    )
                )
            speaker_segments.sort(key=lambda span: (span.start, span.end))
            return speaker_segments
    
        # fallback; plain dictionary with a "segments" list
        if isinstance(diarization_result, dict) and "segments" in diarization_result:
            for row in diarization_result["segments"]:
                speaker_segments.append(
                    SpeakerSegment(
                        start=float(row.get("start", 0.0)),
                        end=float(row.get("end", 0.0)),
                        label=str(row.get("speaker") or row.get("label") or "UNKNOWN"),
                    )
                )
            speaker_segments.sort(key=lambda span: (span.start, span.end))
            return speaker_segments
        else: return []

    speaker_segments: List[SpeakerSegment] = normalize_diarization(diarization_result)

    if not speaker_segments:
        # if diarization produced nothing usable always return unknown
        def speaker_for_interval(start_time: float, end_time: float) -> str: return "UNKNOWN"
    else:
        # segment_index is a faux pointer that points to the first diarization segment that could possibly overlap the current transcription segment
        segment_index: int = 0
        def speaker_for_interval(start_time: float, end_time: float) -> str:
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

            # scan onward from segment_index to find overlapping spans and get the one with maximum overlap
            i:int = segment_index
            while i < n_of_segments:
                span = speaker_segments[i]
                if span.start >= end_time: break # once the start of the span is at or after the end time no further overlaps are possible
                overlap_seconds: float = max(0.0, min(end_time, span.end) - max(start_time, span.start),)
                if overlap_seconds > max_overlap_seconds: max_overlap_seconds = overlap_seconds; best_label = span.label # update the best label if computed overlap is strictly larger than any previous
                i += 1

            if best_label is not None: return best_label

            # fallback if no overlap -- use the midpoint of the interval to look for a containing span
            midpoint_second: float = 0.5 * (start_time + end_time)
            i = segment_index
            while i < n_of_segments:
                span = speaker_segments[i]
                if span.start <= midpoint_second < span.end: return span.label # if the midpoint lies within this span use its label
                if span.start > midpoint_second: break # once the start of the span is after the midpoint no later span can contain it
                i += 1

            return "UNKNOWN"
        
    # label each segment with a speaker
    labeled_segments: List[Utterance] = []
    for segment in cleaned_segments:
        speaker_label: str = speaker_for_interval(segment.start, segment.end)
        labeled_segments.append(Utterance(start=segment.start, end=segment.end, speaker=speaker_label, text=segment.text,))
    labeled_segments.sort(key=lambda segment: (segment.start, segment.end))

    def merge_text(previous_text: str, next_text: str) -> str:
        """
        merges two text fragments into a single string; avoids double spaces, missing spaces between words, and spaces before punctuation
        
        if the previous text ends with whitespace, dash, or an opening punctuation do not add a space
        if the new segment starts with closing or separating punctuation do not add a space
        otherwise add a space
        """
        if not next_text: return previous_text # nothing to merge
        if not previous_text: return (next_text or "").lstrip() # the merged result is just the new segment text

        next_text = next_text.lstrip()
        starts_with_punctuation = bool(next_text) and next_text[0] in ".,!?;:%)]}"
        ends_with_something_to_follow = previous_text.endswith((" ", "\n", "—", "-", "(", "[", "{", "“", "'")) # i really don't know what to name this variable
        if not starts_with_punctuation and not ends_with_something_to_follow: return previous_text + " " + next_text

        return previous_text + next_text

    # merge consecutive segments from the same speaker into longer utterances
    utterances: List[Utterance] = []
    for segment in labeled_segments:
        if (utterances and utterances[-1].speaker == segment.speaker and (segment.start - utterances[-1].end) <= speaker_gap_threshold):
            last_utterance: Utterance = utterances[-1]
            last_utterance.text = merge_text(last_utterance.text, segment.text or "")
            last_utterance.end = segment.end
        else: utterances.append(Utterance(start=segment.start, end=segment.end, speaker=segment.speaker, text=segment.text)) # for better scoping

    return [{"start": utterance.start, "end": utterance.end, "speaker": utterance.speaker, "text": utterance.text} for utterance in utterances]

def transcribe_with_diarization(audio_path: Path, model, output_path: Path, output_format: str) -> None:
    """
    this basically just calls all the functions above to make the full transcription pipeline and write the result to disk
    also computes and prints the time the script took processing the file, i was using that to track how well the script was optimised
    any exception raised in the pipeline steps throws an error and exits the program
    """
    print(f"\nprocessing: {audio_path}")
    start_time: float = time.perf_counter()

    try:
        print("transcribing")
        transcription_result: WordDict = transcribe_audio(audio_path, model) # after model ", DEVICE"
        # torch.cuda.empty_cache() # emptying cache avoids ooms at the cost of processing speed

        print("aligning")
        alignment_result: WordDict = align_transcription(transcription_result["segments"], audio_path)
        # torch.cuda.empty_cache()

        print("diarizing")
        diarization_result = run_diarization(audio_path, HF_TOKEN)
        # torch.cuda.empty_cache()

        print("post processing")
        utterance_lines = postprocess_segments(alignment_result, diarization_result)

    except Exception as e: print(f"{e}"); sys.exit(1)

    end_time: float = time.perf_counter()
    if output_format == "json": file_body = json.dumps({"utterances": utterance_lines}, ensure_ascii=False, indent=2)
    else:
        formatted_lines = [f"[{format_timestamp(utterance_line['start'])}] {utterance_line['speaker']}: {utterance_line['text']}" for utterance_line in utterance_lines]
        file_body = "\n".join(formatted_lines)

    output_path.write_text(file_body, encoding="utf-8")
    print(f"saved to: {output_path}")
    print(f"\ntook {format_duration(end_time-start_time)}")

def overwrite(output_path: Path, overwrite_flag: bool) -> Path:
    """
    decides the filepath to use for the output file

    if overwriting is not permitted:
        if output path does not yet exist return output path
        if output_path already exists recursively add _new to the output path until doesn't yet exist
    """
    if not output_path.exists() or overwrite_flag: return output_path

    # response = input(f"'{output_path}' already exists. overwrite? [y/n]: ").strip().lower()
    # if response == "y": return output_path

    def bump(path: Path) -> Path:
        base = path.stem
        suffix = path.suffix
        new_base = base + "_new"
        candidate = path.with_name(new_base + suffix)

        if candidate.exists(): return bump(candidate)
        return candidate
    
    return bump(output_path)

def delete_wav(wav_path: Path):
    """
    deletes an intermediate .wav if it exists; doesn't exit if couldn't delete
    """
    if wav_path.exists():
        try: wav_path.unlink()
        except Exception as e: print(f"could not delete wav. {e}")

if __name__ == "__main__":
    # total_start_time: float = time.perf_counter()
    parser = argparse.ArgumentParser()
    parser.add_argument("input_file")
    parser.add_argument("--model", default="medium")                                    # can specify a different whisperx model
    parser.add_argument("-v", "--verbose", action="store_true")                         # doesn't supress any logs for debugging
    parser.add_argument("-k", "--keep-wav", action="store_true")                        # doesn't delete intermediate .wav
    parser.add_argument('-o', '--overwrite', action='store_true')                       # overwrites any existing outputs
    parser.add_argument('-f', '--out_format', choices=['txt','json'], default='txt')    # deprecate? idk if i will actually ever need .json outputs
    args = parser.parse_args()

    VERBOSE = args.verbose
    suppress_logs()

    # resolve and validate the input path
    input_path = Path(args.input_file)
    if not input_path.is_file():
        print(f"{input_path} does not exist")
        sys.exit(1)

    # decide whether conversion to .wav is necessary
    extension = input_path.suffix.lower()
    if extension == ".wav": wav_path = input_path;  wav_converted = False
    else: wav_path = convert_to_wav(input_path);    wav_converted = True

    # determine output filename
    base_stem = wav_path.stem
    ext = ".json" if args.out_format == "json" else ".txt"
    output_path = Path(f"{base_stem}{ext}")
    output_path = overwrite(output_path, args.overwrite)

    # load whisperx model
    whisper_model = None
    if args.model != parser.get_default("model"):
        try:
            with suppress_everything(): whisper_model = whisperx.load_model(args.model, DEVICE, compute_type="float16")
            # torch.cuda.empty_cache()
        except Exception as e: print(f"model '{args.model}' failed to load. {e}"); sys.exit(1) # if user requested a model that couldnt be loaded
    else:
        try:
            with suppress_everything(): whisper_model = whisperx.load_model("medium", DEVICE, compute_type="float16")
            # torch.cuda.empty_cache()
        except Exception as e: print(f"model '{args.model}' failed to load. {e}"); sys.exit(1) # this should genuinely never happen

    # do the thing!
    try: transcribe_with_diarization(wav_path, whisper_model, output_path, args.out_format)
    finally: 
        # total_end_time: float = time.perf_counter()
        # print(f"\ntotal {format_duration(total_end_time-total_start_time)}")
        if wav_converted and not args.keep_wav: delete_wav(wav_path)
