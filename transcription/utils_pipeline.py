import ffmpeg; import torch; import whisperx
from numpy import ndarray, frombuffer, int16
from shutil import which
from pandas import DataFrame
from whisperx.asr import FasterWhisperPipeline
from utils_types import TranscriptionError, TranscriptionResult, SegmentDict, AlignmentResult
from utils_models import get_align_model, get_diarization_pipeline, get_device, get_whisper_model

DEVICE: str = get_device()
STATES: tuple[str, str, str, str, str, str] = ("idle", "received", "transcribing", "aligning", "diarizing", "post-processing")
_FFMPEG_AVAILABLE: bool = which("ffmpeg") is not None # caching ffmpeg presence so that it's not called repeatedly

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
    """runs speaker diarization on audio via the cached diarization pipeline"""
    diarization_pipeline = get_diarization_pipeline()
    diarization_result: DataFrame = diarization_pipeline(audio, min_speakers=2, max_speakers=5)
    return diarization_result

def postprocess_segments(diarization_result: DataFrame, alignment_result: AlignmentResult) -> bytes:
    """merges word level speakers and timings into final utterances and formats the transcript"""
    alignment_result = whisperx.assign_word_speakers(diarization_result, alignment_result)
    _fill_missing_word_speakers(alignment_result, diarization_result)

    lines: list[str] = []
    for segment in alignment_result.get("segments", []):
        words = [w for w in segment.get("words", []) if isinstance(w, dict) and isinstance(w.get("word"), str)]
        if not words: continue
        start = float(words[0].get("start") or 0.0)
        speaker = str(words[0].get("speaker") or "UNKNOWN")
        text = " ".join(w["word"] for w in words)
        lines.append(f"[{_format_timestamp(start)}] {speaker}: {text}")

    return "\n".join(lines).encode("utf-8")


def _fill_missing_word_speakers(alignment_result: AlignmentResult, diarization_result: DataFrame) -> None:
    """fills missing word "speaker" fields in alignment_result using diarization turns"""
    diarization_intervals = []
    for _, diarization_row in diarization_result.iterrows():
        if "start" in diarization_row and "end" in diarization_row:
            diarization_intervals.append(
                (float(diarization_row["start"]), float(diarization_row["end"]), 
                 str(diarization_row.get("speaker") or diarization_row.get("label") or "")))

    for segment in alignment_result.get("segments", []):
        for word_entry in segment.get("words", []):
            if word_entry.get("speaker"): continue
            word_start = word_entry.get("start")
            if word_start is None: continue
            word_time = float(word_start)
            for interval_start, interval_end, interval_label in diarization_intervals:
                if interval_start <= word_time < interval_end and interval_label:
                    word_entry["speaker"] = interval_label
                    break

def _format_timestamp(total_seconds: float) -> str:
    hours: int = int(total_seconds // 3600)
    minutes: int = int((total_seconds % 3600) // 60)
    seconds: int = int(total_seconds % 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


    