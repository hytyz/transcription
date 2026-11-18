import os; import torch; import whisperx
from numpy import ndarray, frombuffer, clip, dtype
from shutil import which
import subprocess
from pandas import DataFrame
from .dataclasses import TranscriptionError, Segment, alignment_result_from_whisper, \
    alignment_result_to_whisper, transcription_result_from_whisper, segment_to_whisper
from .models import get_align_model, get_diarization_pipeline, get_device, get_whisper_model

DEVICE = get_device()
BATCH_SIZE = int(os.environ.get("BATCH_SIZE", "8"))
_FFMPEG_AVAILABLE = which("ffmpeg") is not None # caching ffmpeg presence so that it's not called repeatedly

def load_audio(path):
    """
    decodes an audio file on disk into a mono 16 khz float32 waveform via ffmpeg
    returns a 1d numpy array with samples normalised to [-1.0, 1.0] per whisperx's wants
    """
    if not _FFMPEG_AVAILABLE: raise TranscriptionError("ffmpeg not found. https://ffmpeg.org/download.html")

    ffmpeg_cmd = [
        "ffmpeg",
        "-nostdin", # disables standard input
        "-loglevel", "error", # only spew out errors
        "-i", path,
        "-ac", "1", # not sure whether setting it to mono actually improves anything
        "-ar", "16000", # sample rate 16 kHz
        "-f", "f32le", # output format pcm 32 bit float little-endian
        "pipe:1", 
    ]

    process = subprocess.run(ffmpeg_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if process.returncode != 0: raise TranscriptionError(process.stderr.decode(errors="ignore"))

    if not process.stdout: raise RuntimeError("decoded audio is empty")
    audio = frombuffer(process.stdout, dtype=dtype("<f4"))
    return clip(audio, -1.0, 1.0)

def transcribe_audio(audio: ndarray):
    whisper_model = get_whisper_model()
    with torch.inference_mode(): raw = whisper_model.transcribe(audio, batch_size=BATCH_SIZE, language="en", task="transcribe")
    return transcription_result_from_whisper(raw)

def align_transcript_segments(audio: ndarray, segments: list[Segment]):
    align_model, align_metadata = get_align_model()
    whisper_segments = [segment_to_whisper(s) for s in segments]
    raw = whisperx.align(whisper_segments, align_model, 
                         {"language": align_metadata.language, 
                          "dictionary": align_metadata.dictionary, 
                          "type": align_metadata.type}, audio, DEVICE)
    return alignment_result_from_whisper(raw)

def run_diarization_pipeline(audio: ndarray) -> DataFrame:
    diarization_pipeline = get_diarization_pipeline()
    diarization_result = diarization_pipeline(audio, min_speakers=2, max_speakers=5)
    return diarization_result

def postprocess_segments(diarization_result: DataFrame, alignment_result) -> bytes:
    aligned_dict = alignment_result_to_whisper(alignment_result)
    aligned_dict = whisperx.assign_word_speakers(diarization_result, aligned_dict, fill_nearest=True)
    alignment_result = alignment_result_from_whisper(aligned_dict)
    # _fill_missing_word_speakers(alignment_result, diarization_result)

    lines = []
    for segment in alignment_result.segments:
        words = [word for word in segment.words if isinstance(word.word, str)]
        if not words: continue
        start = float(words[0].duration.start)
        speaker = str(words[0].speaker or "UNKNOWN")
        text = " ".join(word.word for word in words)
        lines.append(f"[{_format_timestamp(start)}] {speaker}: {text}")
    return "\n".join(lines).encode("utf-8")


# backup in case fill_nearest misbehaves
# def _fill_missing_word_speakers(alignment_result, diarization_result: DataFrame):
#     """
#     fills missing word "speaker" fields in alignment_result using diarization turns
#     builds time intervals from diarization_result and 
#     assigns the interval speaker to words whose start time falls inside an interval"""
#     diarization_intervals = []
#     for _, diarization_row in diarization_result.iterrows():
#         if "start" in diarization_row and "end" in diarization_row:
#             diarization_intervals.append(
#                 (float(diarization_row["start"]), float(diarization_row["end"]),
#                 str(diarization_row.get("speaker") or diarization_row.get("label") or "")))
#
#
#     for segment in alignment_result.segments:
#         for word_entry in segment.words:
#             if word_entry.speaker: continue
#             word_time = float(word_entry.duration.start)
#             for interval_start, interval_end, interval_label in diarization_intervals:
#                 if interval_start <= word_time < interval_end and interval_label:
#                     word_entry.speaker = interval_label
#                     break

def _format_timestamp(total_seconds):
    hours = int(total_seconds // 3600)
    minutes = int((total_seconds % 3600) // 60)
    seconds = int(total_seconds % 60)

    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
