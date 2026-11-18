from numpy import ndarray
from pandas import DataFrame
from .dataclasses import TranscriptionError, TranscriptionResult, AlignmentResult
from .models import get_whisper_model, get_align_model, get_diarization_pipeline
from .pipeline import load_audio, transcribe_audio, align_transcript_segments, run_diarization_pipeline, postprocess_segments
from typing import Callable
from enum import StrEnum

class CurrentState(StrEnum):
    RECEIVED = "received"
    TRANSCRIBING = "transcribing"
    ALIGNING = "aligning"
    DIARIZING = "diarizing"
    POSTPROCESSING = "postprocessing"

def warm_up() -> None:
    get_whisper_model()
    get_align_model()
    get_diarization_pipeline()

def generate_diarized_transcript(audio_path: str, on_status: Callable[[str], None] | None = None) -> bytes:
    try:
        if on_status: on_status(CurrentState.RECEIVED)
        audio: ndarray = load_audio(audio_path)
        if on_status: on_status(CurrentState.TRANSCRIBING)
        transcription_result: TranscriptionResult = transcribe_audio(audio)
        if on_status: on_status(CurrentState.ALIGNING)
        alignment_result: AlignmentResult = align_transcript_segments(audio, transcription_result.segments)
        if on_status: on_status(CurrentState.DIARIZING)
        diarization_result: DataFrame = run_diarization_pipeline(audio)
        if on_status: on_status(CurrentState.POSTPROCESSING)
        transcript_bytes: bytes = postprocess_segments(diarization_result, alignment_result)
        return transcript_bytes
    except TranscriptionError as e: raise TranscriptionError(f"transcription with diarization failed: {e}") from e
    except Exception as e: raise Exception(f"transcription with diarization failed: {e}") from e

__all__ = ["generate_diarized_transcript", "warm_up"]
