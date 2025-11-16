import logging; import warnings; from lightning.pytorch.utilities import disable_possible_user_warnings

def _configure_verbosity(verbose: bool) -> None:
    """
    sets the global VERBOSE flag and configures warnings and logging levels
    """
    global VERBOSE
    VERBOSE = verbose
    root_logger = logging.getLogger()

    if VERBOSE:
        warnings.resetwarnings(); warnings.filterwarnings("default")
        root_logger.setLevel(logging.INFO)
        for handler in root_logger.handlers: handler.setLevel(logging.INFO)
        logging.getLogger("pyannote").setLevel(logging.INFO)
        logging.getLogger("pytorch_lightning").setLevel(logging.INFO)
        logging.getLogger("whisperx").setLevel(logging.INFO)
    else:
        disable_possible_user_warnings(); warnings.filterwarnings("ignore")
        root_logger.setLevel(logging.ERROR)
        for handler in root_logger.handlers: handler.setLevel(logging.ERROR)
        logging.getLogger("pyannote").setLevel(logging.ERROR)
        logging.getLogger("pytorch_lightning").setLevel(logging.ERROR)
        logging.getLogger("whisperx").setLevel(logging.ERROR)

_configure_verbosity(False)

import os; import sys;
import contextlib; import shutil
import subprocess; import math
import whisperx; import torch; import re
# from pydub import AudioSegment
from pathlib import Path
from whisperx.asr import FasterWhisperPipeline
from typing import Optional, List, Any, Iterator, Iterable, Callable, Mapping, Pattern, Tuple
from numpy import ndarray
from utils_types import *

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

def _get_align_model():
    """
    loads and caches the whisperx alignment model and metadata
    subsequent calls reuse the cached objects instead of reloading the model
    """
    global _ALIGN_MODEL, _ALIGN_METADATA
    if _ALIGN_MODEL is None or _ALIGN_METADATA is None: _ALIGN_MODEL, _ALIGN_METADATA = whisperx.load_align_model(language_code="en", device=DEVICE)
    return _ALIGN_MODEL, _ALIGN_METADATA

def _get_diarization_pipeline(speaker_threshold: int):
    
    """
    loads and caches the pyannote diarization pipeline used by whisperx
    subsequent calls reuse the cached pipeline instance
    """
    global _DIARIZATION_PIPELINE
    if _DIARIZATION_PIPELINE is None:
        # TODO find the actual github repo and cite it
        _DIARIZATION_PIPELINE = whisperx.diarize.DiarizationPipeline(model_name="pyannote/speaker-diarization@2.1", use_auth_token=HF_TOKEN, device=DEVICE) # DO NOT CHANGE THIS
        try: _DIARIZATION_PIPELINE.set_params({"clustering": {"threshold": speaker_threshold}}) 
        except Exception as e: 
            if VERBOSE: print(f"could not set diarization clustering threshold: {e}")
    return _DIARIZATION_PIPELINE

# TODO look into deprecating
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

# TODO deprecate
def format_duration(seconds: float) -> str:
    """
    converts a duration in seconds to a readable string
    this is for reporting total processing time to the console
    """
    def _plural(unit: str, value: int) -> str: return f"{value} {unit}" + ("s" if value != 1 else "")
    if seconds < 60: return f"{seconds:.1f} {'second' if int(round(seconds)) == 1 else 'seconds'}"
    minutes, remaining_seconds = divmod(int(seconds), 60)
    if minutes < 60: return f"{_plural('minute', minutes)} and {_plural('second', int(remaining_seconds))}"
    hours, minutes = divmod(minutes, 60)
    return f"{_plural('hour', hours)}, {_plural('minute', minutes)} and {_plural('second', int(remaining_seconds))}"

# try a different way
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
        # "-ac", "1",           # whisperx docs recommend mono but idk aobut that chief
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
    start and end timestamps, and text string
    """     
    with _suppress_everything():
        audio: ndarray = whisperx.load_audio(str(audio_path))
        with torch.inference_mode(): result: TranscriptionResult = model.transcribe(audio, language="en", task="transcribe")
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

def run_diarization(audio_path: Path, speaker_threshold: int) -> DiarizationResult:
    """
    runs speaker diarization on an audio file using the cached pipeline through whisperx
    returns an object describing contiguous time spans for each detected speaker
    """
    with _suppress_everything():
        diarization_pipeline = _get_diarization_pipeline(speaker_threshold)
        diarization_result: DiarizationResult = diarization_pipeline(whisperx.load_audio(str(audio_path)), min_speakers=2, max_speakers=5)
    return diarization_result

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
            # print("tracks")
            speaker_segments.append(SpeakerSegment(start=float(start_value), end=float(end_value), label=str(speaker_label)))

    # fallback; dataframe like object exposing iterrows
    # THIS IS WHERE IT GOES TODO LOOK INTO
    elif callable(iterator_over_rows):
        rows: Iterable[Tuple[Any, Mapping[str, Any]]] = iterator_over_rows()
        for _, row in rows:
            start_value = row.get("start")
            end_value = row.get("end")
            if start_value is None or end_value is None: continue
            # print("rows")

            label_value = row.get("speaker", row.get("label", "UNKNOWN"))
            speaker_segments.append(SpeakerSegment(start=float(start_value), end=float(end_value), label=str(label_value)))

    # fallback; plain dictionary with a "segments" list
    elif isinstance(diarization_result, dict) and "segments" in diarization_result:
        for row_values in diarization_result["segments"]:
            start_value = row_values.get("start")
            end_value = row_values.get("end")
            if start_value is None or end_value is None: continue
            
            # print("dictionary")

            label_value = row_values.get("speaker") or row_values.get("label") or "UNKNOWN"
            speaker_segments.append(SpeakerSegment(start=float(start_value), end=float(end_value), label=str(label_value)))

    cleaned_segments: List[SpeakerSegment] = []
    for speaker_span in speaker_segments:
        start_seconds: float = float(speaker_span.start)
        end_seconds: float = float(speaker_span.end)
        if not (math.isfinite(start_seconds) and math.isfinite(end_seconds)): continue
        if start_seconds < 0.0: start_seconds = 0.0
        if end_seconds < 0.0: end_seconds = 0.0
        if end_seconds <= start_seconds: continue
        cleaned_segments.append(SpeakerSegment(start=start_seconds, end=end_seconds, label=speaker_span.label))

    cleaned_segments.sort(key=lambda segment: (segment.start, segment.end))
    return cleaned_segments

def _default_speaker_for_interval(interval_start: float, interval_end: float, turns: List[SpeakerSegment]) -> Optional[str]:
    """
    # TODO REWRITE
    picks a default speaker label for a time interval using diarization turns
    returns the speaker label with maximum overlap or None if there is no overlap
    """
    best_label: Optional[str] = None
    best_overlap: float = 0.0
    for turn in turns:
        overlap_start: float = max(interval_start, turn.start)
        overlap_end: float = min(interval_end, turn.end)
        if overlap_end <= overlap_start: continue
        overlap_duration: float = overlap_end - overlap_start
        if overlap_duration > best_overlap:
            best_overlap = overlap_duration
            best_label = turn.label
    return best_label

def _fill_missing_word_speakers(alignment_result: AlignmentResult, diarization_result: DiarizationResult) -> None:
    """
    gives words in alignment_result speaker labels

    steps:
        1. normalises diarization_result into a sorted list of speaker turns via _normalize_diarization_turns
        2. sets each segment and its words in order
        3. for words missing a "speaker" field:
            picks a label from overlapping diarization turns when available
            otherwise falls back to the previous word label in the same segment
        4. leaves words that still cannot be labeled unchanged

    mutates alignment_result and doesn't return anything
    """
    segments: List[SegmentDict] = alignment_result.get("segments") or []
    if not isinstance(segments, list): raise TranscriptionError("alignment_result must contain a segments list")
    turns: List[SpeakerSegment] = _normalize_diarization_turns(diarization_result)
    for segment in segments:
        words = segment.get("words") or []
        previous_label: Optional[str] = None # last known label inside this segment; used as a fallback
        for word in words:
            if not isinstance(word.get("start"), (int, float)) or not isinstance(word.get("end"), (int, float)): continue
            # already labeled by assign_word_speakers; remember and move on
            if "speaker" in word and word["speaker"]: previous_label = str(word["speaker"]); continue
            # primary source for backfilling -- label derived from overlapping diarization turns
            label: Optional[str] = _default_speaker_for_interval(float(word["start"]), float(word["end"]), turns)
            if label is None and previous_label is not None: label = previous_label
            else: label = previous_label
            if label is None: continue #; print("label is none on line 362")
            word["speaker"] = label
            previous_label = label

def postprocess_segments(alignment_result: AlignmentResult, speaker_gap_threshold: float = 0.8) -> List[Utterance]:
    """
    merges word-level speaker labels into utterances using diarization turns as time boundaries. core logic

    params:
    alignment_result comes from whisperx.assign_word_speakers
    diarization_result is a pyannote-style object, DataFrame, or dict
    speaker_gap_threshold is the maximum permitted silence when merging words and utterances for the same speaker
    
    # TODO REWRITE
    steps:
        1. normalises diarization_result into a sorted list of speaker turns
        2. for segments without words, picks the label with longest overlap and emits one utterance
        3. for segments with words:
            splits by turn boundaries into subintervals
            derives a default speaker per subinterval from overlapping turns
            for each word uses its own "speaker", the interval default, or "UNKNOWN"
        4. groups consecutive words with the same label and gap <= speaker_gap_threshold into utterances
        5. sorts utterances and merges adjacent utterances from the same speaker when the gap <= speaker_gap_threshold

    returns chronologically sorted utterances
    """
    segments: List[SegmentDict] = alignment_result.get("segments")
    if not isinstance(segments, list): raise TranscriptionError("alignment_result must contain a segments list")

    # collect all well formed word entries from all segments
    word_entries: List[Mapping[str, Any]] = []
    for segment in segments:
        segment_words: List[Mapping[str, Any]] = segment.get("words") or []
        for word_entry in segment_words:
            if not isinstance(word_entry.get("start"), (int, float)): continue
            if not isinstance(word_entry.get("end"), (int, float)): continue
            if not isinstance(word_entry.get("word"), str): continue
            word_entries.append(word_entry)

    # ensure a global chronological order before grouping
    word_entries.sort(key=lambda word_entry: float(word_entry["start"]))

    utterances: List[Utterance] = []
    leading_punctuation_regex: Pattern[str] = re.compile(r"^[\.\,\!\?\;\:\%\)\]\}]")

    def _merge_text(previous_text: str, next_text: str) -> str:
        """
        merges two strings, inserting spaces only when appropriate
        """
        previous_text = (previous_text or "").rstrip()
        next_text = (next_text or "").lstrip()
        if not previous_text: return next_text  # the merged result is just the new text
        if not next_text: return previous_text  # nothing to append
        last_char: str = previous_text[-1]
        if last_char in "-([{\"'": return previous_text + next_text
        if leading_punctuation_regex.match(next_text): return previous_text + next_text 
        return previous_text + " " + next_text

    # current in progress utterance state
    current_speaker: Optional[str] = None  # label of the current speaker run
    current_words: List[Mapping[str, Any]] = []  # words collected for the current speaker run

    # first pass; build utterances directly from words and their speaker labels
    for word_entry in word_entries:
        raw_label: Any = word_entry.get("speaker")
        start_seconds: float = float(word_entry["start"])
        # no label. either attach to the current utterance when close enough or flush the current one and skip
        if not raw_label and current_words:
            gap_seconds: float = start_seconds - float(current_words[-1]["end"])
            # treat unlabeled word as belonging to the current speaker when the gap is small
            if gap_seconds <= speaker_gap_threshold and current_speaker is not None: current_words.append(word_entry); continue
            # flush any existing utterance before dropping the unlabeled word
            if current_words and current_speaker is not None:
                text: str = ""
                for current_word in current_words: text = _merge_text(text, str(current_word["word"]))
                utterances.append(Utterance(
                    start=float(current_words[0]["start"]),
                    end=float(current_words[-1]["end"]),
                    speaker=str(current_speaker),
                    text=text.strip()))
            current_speaker = None  # reset speaker state because we lost continuity
            current_words = []      # clear collected words
            continue

        label: str = str(raw_label)
        if not current_words: current_speaker = label; current_words = [word_entry]; continue # starting a new utterance run

        gap_seconds: float = start_seconds - float(current_words[-1]["end"])

        # TODO explain
        if label == current_speaker and gap_seconds <= speaker_gap_threshold: current_words.append(word_entry)
        else:
            # speaker changed or gap too long -- flush the current utterance and start a new one
            text = ""
            for current_word in current_words: text = _merge_text(text, str(current_word["word"]))
            utterances.append(Utterance(
                start=float(current_words[0]["start"]),
                end=float(current_words[-1]["end"]),
                speaker=str(current_speaker),
                text=text.strip()))
            current_speaker = label
            current_words = [word_entry]

    # flush any remaining utterance after the loop
    if current_words and current_speaker is not None:
        text = ""
        for current_word in current_words: text = _merge_text(text, str(current_word["word"]))
        utterances.append(Utterance(
            start=float(current_words[0]["start"]),
            end=float(current_words[-1]["end"]),
            speaker=str(current_speaker),
            text=text.strip()))

    # second pass; merge adjacent utterances for the same speaker when close in time
    merged_utterances: List[Utterance] = []
    for utterance in utterances:
        if not merged_utterances: merged_utterances.append(utterance); continue

        last_utterance = merged_utterances[-1]
        gap_seconds = max(0.0, float(utterance.start) - float(last_utterance.end))

        if utterance.speaker == last_utterance.speaker and gap_seconds <= speaker_gap_threshold:
            # same speaker and short gap. extend the previous utterance boundaries and text
            merged_utterances[-1] = Utterance(
                start=last_utterance.start,
                end=max(last_utterance.end, utterance.end),
                speaker=last_utterance.speaker,
                text=_merge_text(last_utterance.text, utterance.text))
        else: merged_utterances.append(utterance) # different speaker or long silence -- start a new utterance

    return merged_utterances