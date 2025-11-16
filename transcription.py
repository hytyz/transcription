from numpy import ndarray
from typing import Callable, Optional
from pandas import DataFrame
from utils_types import TranscriptionError, TranscriptionResult, AlignmentResult
from utils_functions import STATES, load_audio, transcribe_audio, align_transcript_segments, run_diarization_pipeline, postprocess_segments

CURRENT_STATE: str = ""

def get_current_state() -> str:
    """
    returns the current pipeline state label for the most recent job
    """
    return CURRENT_STATE

def generate_diarized_transcript(audio_bytes: bytes, on_state_change: Optional[Callable[[str], None]] = None) -> bytes:
    """
    runs the full transcription and diarization pipeline on an in-memory audio blob
    returns the formatted transcript as utf8 encoded bytes
    """
    def _set_state(state_index: int) -> None:
        global CURRENT_STATE
        CURRENT_STATE = STATES[state_index]
        if on_state_change is not None: on_state_change(CURRENT_STATE)

    try:
        _set_state(0)
        audio: ndarray = load_audio(audio_bytes)

        _set_state(1)
        transcription_result: TranscriptionResult = transcribe_audio(audio)

        _set_state(2)
        alignment_result: AlignmentResult = align_transcript_segments(audio, transcription_result["segments"])

        _set_state(3)
        diarization_result: DataFrame = run_diarization_pipeline(audio)

        _set_state(4)
        transcript_bytes: bytes = postprocess_segments(diarization_result, alignment_result)

        return transcript_bytes
    except TranscriptionError: raise
    except Exception as e: raise Exception(f"transcription with diarization failed: {e}") from e
