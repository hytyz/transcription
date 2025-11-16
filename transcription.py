from numpy import ndarray
from typing import Callable, Optional
from utils_types import TranscriptionError, TranscriptionResult, AlignmentResult, DiarizationResult
from utils_functions import STATES, load_audio, transcribe_audio, align_transcription, run_diarization, postprocess_segments

CURRENT_STATE: str = ""

def get_current_state() -> str:
    """
    returns the current pipeline state label for the most recent job
    """
    return CURRENT_STATE

def transcribe_with_diarization(audio_bytes: bytes, on_state_change: Optional[Callable[[str], None]] = None) -> bytes:
    """
    runs the full transcription and diarization pipeline on an in-memory audio blob
    returns the formatted transcript as utf8 encoded bytes
    """
    global CURRENT_STATE

    def _set_state(state_index: int) -> None:
        global CURRENT_STATE
        CURRENT_STATE = STATES[state_index]
        if on_state_change is not None: on_state_change(CURRENT_STATE)

    try:
        _set_state(0)
        audio: ndarray = load_audio(audio_bytes)

        _set_state(1)
        print("transcribing")
        transcription_result: TranscriptionResult = transcribe_audio(audio)
        # torch.cuda.empty_cache() # emptying cache avoids ooms at the cost of processing speed

        _set_state(2)
        print("aligning")
        alignment_result: AlignmentResult = align_transcription(audio, transcription_result["segments"])
        # torch.cuda.empty_cache()

        _set_state(3)
        print("diarizing")
        diarization_result: DiarizationResult = run_diarization(audio)
        # torch.cuda.empty_cache()

        _set_state(4)
        print("post processing")
        transcript_bytes: bytes = postprocess_segments(diarization_result, alignment_result)
        return transcript_bytes
    except Exception as e: raise TranscriptionError(f"transcription with diarization failed: {e}") from e
