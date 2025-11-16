import math; import re; import shutil
from typing import Optional, List, Mapping, Iterable, Callable, Pattern, Tuple
import ffmpeg; import numpy; import torch
import whisperx; from numpy import ndarray
from utils_types import *
from utils_models import get_align_model, get_diarization_pipeline, get_device, load_whisper_model
from whisperx.asr import FasterWhisperPipeline

DEVICE: str = get_device()
SPEAKER_GAP_THRESHOLD: float = 0.7 # maximum permitted silence when merging words and utterances for the same speaker
STATES: Tuple[str, str, str, str, str] = ("received", "transcribing", "aligning", "diarizing", "post-processing")

def _format_timestamp(total_seconds: float) -> str:
    """
    converts a timestamp in seconds to hh:mm:ss (like 3661.3 to 01:01:01)
    """
    hours: int = int(total_seconds // 3600)
    minutes: int = int((total_seconds % 3600) // 60)
    seconds: int = int(total_seconds % 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"

def load_audio(data:bytes) -> ndarray:
    """
    decodes an audio byte stream into a mono 16 khz float32 waveform via ffmpeg
    returns a 1d numpy array with samples normalized to [-1.0, 1.0]
    """
    if not shutil.which("ffmpeg"): raise TranscriptionError("ffmpeg not found. https://ffmpeg.org/download.html")

    process = (ffmpeg.input("pipe:0")
               .output("pipe:1", format="s16le", acodec="pcm_s16le", ac=1, ar="16000")
               .run_async(pipe_stdin=True, pipe_stdout=True, pipe_stderr=True))
    out: bytes
    err: bytes
    out, err = process.communicate(input = data)
    if process.returncode != 0: raise TranscriptionError(f"ffmpeg decoding failed: {err.decode(errors='ignore')}")
    
    audio = numpy.frombuffer(out, dtype=numpy.int16)
    if audio.size == 0: raise TranscriptionError("decoded audio is empty")
    return audio.astype("float32") / 32768.0


def transcribe_audio(audio: ndarray) -> TranscriptionResult:
    """
    performs transcription on the given audio using a preloaded whisperx model
    uses torch.inference_mode() to disable gradient tracking for speed and lower memory usage

    returns a dictionary with the raw transcription output: segments is a list of segments, each including
    start and end timestamps, and text string
    """
    whisper_model: FasterWhisperPipeline = load_whisper_model()
    with torch.inference_mode(): result: TranscriptionResult = whisper_model.transcribe(audio, language="en", task="transcribe")
    return result

def align_transcription(audio: ndarray, segments: List[SegmentDict]) -> AlignmentResult:
    """
    aligns raw whisperx segments with the audio via the cached whisperx alignment model
    takes the segment list from a TranscriptionResult and returns an AlignmentResult 
        its "segments" list preserves the original segment-level fields and adds word-level timing information in a "words" field
    """
    align_model, align_metadata = get_align_model()
    alignment_result: AlignmentResult = whisperx.align(segments, align_model, align_metadata, audio, DEVICE)
    return alignment_result

def run_diarization(audio: ndarray) -> DiarizationResult:
    """
    runs speaker diarization on an audio file using the cached pipeline through whisperx
    returns an object describing contiguous time spans for each detected speaker
    """
    diarization_pipeline = get_diarization_pipeline()
    diarization_result: DiarizationResult = diarization_pipeline(audio, min_speakers=2, max_speakers=5)
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
            speaker_segments.append(SpeakerSegment(start=float(start_value), end=float(end_value), label=str(speaker_label)))

    # fallback; dataframe like object exposing iterrows
    # THIS IS WHERE IT GOES TODO LOOK INTO
    elif callable(iterator_over_rows):
      for _, row in iterator_over_rows():
          if not isinstance(row, Mapping): continue
          start_value = row.get("start")
          end_value = row.get("end")
          if start_value is None or end_value is None: continue
          label_value = row.get("speaker", row.get("label", "UNKNOWN"))
          speaker_segments.append(SpeakerSegment(start=float(start_value), end=float(end_value), label=str(label_value)))


    # fallback; plain dictionary with a "segments" list
    elif isinstance(diarization_result, dict) and "segments" in diarization_result:
        for list_values in diarization_result["segments"]:
            start_value = list_values.get("start")
            end_value = list_values.get("end")
            if start_value is None or end_value is None: continue
            label_value = list_values.get("speaker") or list_values.get("label") or "UNKNOWN"
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
            if label is None: continue #; print("label is none on line 362")
            word["speaker"] = label
            previous_label = label

def postprocess_segments(diarization_result: DiarizationResult, alignment_result: AlignmentResult) -> bytes:
    """
    merges word level speakers and timings into final utterances and formats the transcript

    params:
    diarization_result is a pyannote style object, dataframe, or dict with diarization turns
    alignment_result is the raw alignment output from whisperx.align with segments and words

    steps:
        1. runs whisperx.assign_word_speakers and _fill_missing_word_speakers to attach a speaker label to as many words as possible
        2. flattens all well formed word entries into a chronogical list of {start, end, word, speaker}
        3. iterates over word list and builds Utterance runs by grouping consecutive words with the same speaker
        4. merges adjacent Utterance objects for the same speaker when the silence between them is <= SPEAKER_GAP_THRESHOLD
        5. formats the merged utterances as "[hh:mm:ss] speaker_xx: text" lines

    returns the final transcript as utf8 encoded bytes
    """
    alignment_result = whisperx.assign_word_speakers(diarization_result, alignment_result)
    _fill_missing_word_speakers(alignment_result, diarization_result)

    segments: List[SegmentDict] = alignment_result.get("segments")
    if not isinstance(segments, list): raise TranscriptionError("alignment_result must contain a segments list")

    # collect all well formed word entries from all segments
    word_entries: List[WordEntry] = []
    for segment in segments:
        segment_words: List[WordEntry] = segment.get("words") or []
        if not isinstance(segment_words, list): continue
        for word_entry in segment_words:
            if not isinstance(word_entry, dict): continue
            start_val = word_entry.get("start")
            end_val = word_entry.get("end")
            word_text = word_entry.get("word")
            if not isinstance(start_val, (int, float)) or not isinstance(end_val, (int, float)): continue
            if not isinstance(word_text, str): continue
            entry: WordEntry = {
                "start": float(start_val),
                "end": float(end_val),
                "word": word_text,
                "speaker": word_entry.get("speaker"),}
            word_entries.append(entry)

    # ensure a global chronological order before grouping
    word_entries.sort(key=lambda word_entry: word_entry["start"])


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
    current_words: List[WordEntry] = []  # words collected for the current speaker run

    # first pass; build utterances directly from words and their speaker labels
    for word_entry in word_entries:
        raw_label = word_entry["speaker"]
        start_seconds: float = float (word_entry["start"])
        # no label. either attach to the current utterance when close enough or flush the current one and skip
        if not raw_label and current_words:
            gap_seconds: float = start_seconds - float (current_words[-1]["end"])
            # treat unlabeled word as belonging to the current speaker when the gap is small
            if gap_seconds <= SPEAKER_GAP_THRESHOLD and current_speaker is not None: current_words.append(word_entry); continue
            # flush any existing utterance before dropping the unlabeled word
            if current_words and current_speaker is not None:
                text: str = ""
                for current_word in current_words: text = _merge_text(text, str(current_word["word"]))
                utterances.append(Utterance(
                    start = float (current_words[0]["start"]),
                    end = float (current_words[-1]["end"]),
                    speaker=str(current_speaker),
                    text=text.strip()))
            current_speaker = None  # reset speaker state because we lost continuity
            current_words = []      # clear collected words
            continue

        label: str = str(raw_label)
        if not current_words: current_speaker = label; current_words = [word_entry]; continue # starting a new utterance run

        gap_seconds: float = start_seconds - float (current_words[-1]["end"])

        # TODO explain
        if label == current_speaker and gap_seconds <= SPEAKER_GAP_THRESHOLD: current_words.append(word_entry)
        else:
            # speaker changed or gap too long -- flush the current utterance and start a new one
            text = ""
            for current_word in current_words: text = _merge_text(text, str(current_word["word"]))
            utterances.append(Utterance(
                start=float (current_words[0]["start"]),
                end=float (current_words[-1]["end"]),
                speaker=str(current_speaker),
                text=text.strip()))
            current_speaker = label
            current_words = [word_entry]

    # flush any remaining utterance after the loop
    if current_words and current_speaker is not None:
        text = ""
        for current_word in current_words: text = _merge_text(text, str(current_word["word"]))
        utterances.append(Utterance(
            start=float (current_words[0]["start"]),
            end=float (current_words[-1]["end"]),
            speaker=str(current_speaker),
            text=text.strip()))

    # second pass; merge adjacent utterances for the same speaker when close in time
    merged_utterances: List[Utterance] = []
    for utterance in utterances:
        if not merged_utterances: merged_utterances.append(utterance); continue

        last_utterance = merged_utterances[-1]
        gap_seconds = max(0.0, float(utterance.start) - float(last_utterance.end))

        if utterance.speaker == last_utterance.speaker and gap_seconds <= SPEAKER_GAP_THRESHOLD:
            # same speaker and short gap. extend the previous utterance boundaries and text
            merged_utterances[-1] = Utterance(
                start=last_utterance.start,
                end=max(last_utterance.end, utterance.end),
                speaker=last_utterance.speaker,
                text=_merge_text(last_utterance.text, utterance.text))
        else: merged_utterances.append(utterance) # different speaker or long silence -- start a new utterance

    # formats the output of the merged utterances list into "[hh:mm:ss] speaker_xx: text" 
    formatted_lines: List[str] = [
        f"[{_format_timestamp(utterance_line.start)}] {utterance_line.speaker}: {utterance_line.text}" 
        for utterance_line in merged_utterances]
    file_body: str = "\n".join(formatted_lines)
    return file_body.encode("utf-8")
