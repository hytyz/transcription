from numpy import ndarray
from pandas import DataFrame
from utils_types import TranscriptionError, TranscriptionResult, AlignmentResult
from utils_pipeline import load_audio, transcribe_audio, align_transcript_segments, run_diarization_pipeline, postprocess_segments

def generate_diarized_transcript(audio_bytes: bytes) -> bytes:
    """runs transcription, alignment, diarization, and formatting for a single audio blob"""
    try:
        audio: ndarray = load_audio(audio_bytes)
        transcription_result: TranscriptionResult = transcribe_audio(audio)
        alignment_result: AlignmentResult = align_transcript_segments(audio, transcription_result["segments"])
        diarization_result: DataFrame = run_diarization_pipeline(audio)
        transcript_bytes: bytes = postprocess_segments(diarization_result, alignment_result)
        return transcript_bytes
    except TranscriptionError as e: raise TranscriptionError(f"transcription with diarization failed: {e}") from e
    except Exception as e: raise Exception(f"transcription with diarization failed: {e}") from e
