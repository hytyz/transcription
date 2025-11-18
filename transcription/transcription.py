from numpy import ndarray
from typing import Callable
from pandas import DataFrame
from utils_types import TranscriptionError, TranscriptionResult, AlignmentResult
from utils_pipeline import STATES, load_audio, transcribe_audio, align_transcript_segments, run_diarization_pipeline, postprocess_segments

current_state: str = "idle"

def get_current_state() -> str: return current_state

def generate_diarized_transcript(audio_bytes: bytes, on_state_change: Callable[[str], None] | None = None) -> bytes:
    """runs transcription, alignment, diarization, and formatting for a single audio blob"""
    def _set_state(state_index: int) -> None:
        global current_state
        current_state = STATES[state_index]
        if on_state_change is not None: on_state_change(current_state)
    try:
        _set_state(1)
        audio: ndarray = load_audio(audio_bytes)
        _set_state(2)
        transcription_result: TranscriptionResult = transcribe_audio(audio)
        _set_state(3)
        alignment_result: AlignmentResult = align_transcript_segments(audio, transcription_result["segments"])
        _set_state(4)
        diarization_result: DataFrame = run_diarization_pipeline(audio)
        _set_state(5)
        transcript_bytes: bytes = postprocess_segments(diarization_result, alignment_result)
        return transcript_bytes
    except TranscriptionError as e: raise TranscriptionError(f"transcription with diarization failed: {e}") from e
    except Exception as e: raise Exception(f"transcription with diarization failed: {e}") from e
    finally: _set_state(0) # reset current status even if threw exception
