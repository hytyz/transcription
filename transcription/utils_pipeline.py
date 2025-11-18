import ffmpeg; import torch; import whisperx
from numpy import ndarray, frombuffer, int16
from shutil import which
from pandas import DataFrame
from whisperx.asr import FasterWhisperPipeline
from utils_types import TranscriptionError, TranscriptionResult, SegmentDict, AlignmentResult, WordEntry, Utterance
from utils_models import get_align_model, get_diarization_pipeline, get_device, get_whisper_model
from utils_postprocess import fill_missing_word_speakers, format_timestamp, merge_text

DEVICE: str = get_device()
STATES: tuple[str, str, str, str, str, str] = ("idle", "received", "transcribing", "aligning", "diarizing", "post-processing")
_FFMPEG_AVAILABLE: bool = which("ffmpeg") is not None # caching ffmpeg presence so that it's not called repeatedly
_SPEAKER_GAP_THRESHOLD: float = 0.7 # maximum permitted silence when merging words and utterances for the same speaker

def load_audio(data:bytes) -> ndarray:
    """
    decodes an audio byte stream into a mono 16 khz float32 waveform via ffmpeg
    returns a 1d numpy array with samples normalised to [-1.0, 1.0]
    """
    if not _FFMPEG_AVAILABLE: raise TranscriptionError("ffmpeg not found. https://ffmpeg.org/download.html")

    process = (ffmpeg.input("pipe:0")
               .output("pipe:1", format="s16le", acodec="pcm_s16le", ac=1, ar="16000")
               .run_async(pipe_stdin=True, pipe_stdout=True, pipe_stderr=True))
    out: bytes
    err: bytes
    out, err = process.communicate(input=data)
    if process.returncode != 0: raise TranscriptionError(f"ffmpeg decoding failed: {err.decode(errors='ignore')}")
    
    audio = frombuffer(out, dtype=int16)
    if audio.size == 0: raise TranscriptionError("decoded audio is empty")
    return audio.astype("float32") / 32768.0

def transcribe_audio(audio: ndarray) -> TranscriptionResult:
    """run transcription on audio and return raw segments via cached whisperx model"""
    whisper_model: FasterWhisperPipeline = get_whisper_model()
    with torch.inference_mode(): result: TranscriptionResult = whisper_model.transcribe(audio, language="en", task="transcribe")
    return result

def align_transcript_segments(audio: ndarray, segments: list[SegmentDict]) -> AlignmentResult:
    """aligns raw whisperx segments to audio via the cached alignment model"""
    align_model, align_metadata = get_align_model()
    alignment_result: AlignmentResult = whisperx.align(segments, align_model, align_metadata, audio, DEVICE)
    return alignment_result

def run_diarization_pipeline(audio: ndarray) -> DataFrame:
    """
    runs speaker diarization on audio via the cached diarization pipeline
    returns a pandas DataFrame of time spans for each detected speaker
    """
    diarization_pipeline = get_diarization_pipeline()
    diarization_result: DataFrame = diarization_pipeline(audio, min_speakers=2, max_speakers=5)
    return diarization_result

def postprocess_segments(diarization_result: DataFrame, alignment_result: AlignmentResult) -> bytes:
    """
    merges word level speakers and timings into final utterances and formats the transcript

    uses diarization to fill missing word speakers, groups consecutive words by speaker and time gaps,
    merges nearby utterances for the same speaker, and returns lines like "[hh:mm:ss] SPEAKER: text" as UTF-8 bytes
    """
    alignment_result = whisperx.assign_word_speakers(diarization_result, alignment_result)
    fill_missing_word_speakers(alignment_result, diarization_result)

    segments: list[SegmentDict] = alignment_result.get("segments")
    if not isinstance(segments, list): raise TranscriptionError("alignment_result must contain a segments list")

    # collect all well formed word entries from all segments
    word_entries: list[WordEntry] = []
    for segment in segments:
        raw_words = segment.get("words") or []
        if not isinstance(raw_words, list): continue
        segment_words: list[WordEntry] = raw_words
        for word_entry in segment_words:
            if not isinstance(word_entry, dict): continue
            start_val = word_entry.get("start")
            end_val = word_entry.get("end")
            word_text = word_entry.get("word")
            if not isinstance(start_val, (int, float)) or not isinstance(end_val, (int, float)): continue
            if not isinstance(word_text, str): continue
            entry: WordEntry = {"start": float(start_val), "end": float(end_val), "word": word_text, "speaker": word_entry.get("speaker")}
            word_entries.append(entry)

    # ensure a global chronological order before grouping
    word_entries.sort(key=lambda word_entry: word_entry["start"])
    utterances: list[Utterance] = []

    # current in progress utterance state
    current_speaker: str | None = None  # label of the current speaker run
    current_words: list[WordEntry] = []  # words collected for the current speaker run

    def _flush_run() -> None:
        """flushes the collected words into an utterance with the current speaker and clears the run state"""
        nonlocal current_words, current_speaker, utterances
        if not current_words: return
        if current_speaker is None: current_speaker = "UNKNOWN"
        text = ""
        for current_word in current_words: text = merge_text(text, str(current_word["word"]))
        utterances.append(Utterance(
            start=float(current_words[0]["start"]), 
            end=float(current_words[-1]["end"]), 
            speaker=str(current_speaker), 
            text=text.strip()))
        current_words = []

    # first pass; build utterances directly from words and their speaker labels
    for word_entry in word_entries:
        raw_label = word_entry["speaker"]
        start_seconds: float = float(word_entry["start"])
        # no label. either attach to the current utterance when close enough or flush the current one and skip
        if not raw_label:
            if not current_words:
                word_entry["speaker"] = "UNKNOWN"
                current_speaker = "UNKNOWN"
                current_words = [word_entry]
                continue
            gap_seconds: float = max(0.0, start_seconds - float(current_words[-1]["end"]))
            if gap_seconds <= _SPEAKER_GAP_THRESHOLD:
                word_entry["speaker"] = str(current_speaker)
                current_words.append(word_entry)
                continue
            _flush_run()
            current_speaker = "UNKNOWN"
            word_entry["speaker"] = current_speaker
            current_words = [word_entry]
            continue

        label: str = str(raw_label)
        if not current_words:
            current_speaker = label
            current_words = [word_entry]
            continue
        gap_seconds: float = max(0.0, start_seconds - float(current_words[-1]["end"]))

        # if the new word has the same speaker as the current and the silence before it is short enough,
        # extend the current utterance by appending this word and keep going    
        if label == current_speaker and gap_seconds <= _SPEAKER_GAP_THRESHOLD: current_words.append(word_entry)
        else:
            _flush_run()
            current_speaker = label
            current_words = [word_entry]
    _flush_run()
    
    # second pass; merge adjacent utterances for the same speaker when close in time
    merged_utterances: list[Utterance] = []
    for utterance in utterances:
        if not merged_utterances:
            merged_utterances.append(utterance)
            continue
        last_utterance = merged_utterances[-1]
        gap_seconds = max(0.0, float(utterance.start) - float(last_utterance.end))
        if utterance.speaker == last_utterance.speaker and gap_seconds <= _SPEAKER_GAP_THRESHOLD:
            # same speaker and short gap. extend the previous utterance boundaries and text
            merged_utterances[-1] = Utterance(
                start=last_utterance.start,
                end=max(last_utterance.end, utterance.end),
                speaker=last_utterance.speaker,
                text=merge_text(last_utterance.text, utterance.text))
        else: merged_utterances.append(utterance) # different speaker or long silence -- start a new utterance

    # formats the output of the merged utterances list into "[hh:mm:ss] speaker_xx: text" 
    formatted_lines: list[str] = [
        f"[{format_timestamp(utterance_line.start)}] {utterance_line.speaker}: {utterance_line.text}" 
        for utterance_line in merged_utterances]
    file_body: str = "\n".join(formatted_lines)
    return file_body.encode("utf-8")
