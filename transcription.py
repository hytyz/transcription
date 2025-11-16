from numpy import ndarray
from utils_types import TranscriptionError, TranscriptionResult, AlignmentResult, DiarizationResult
from utils_functions import load_audio, transcribe_audio, align_transcription, run_diarization, postprocess_segments

def transcribe_with_diarization(audio_bytes: bytes) -> bytes:
    """
    runs the full transcription and diarization pipeline on an in-memory audio blob
    returns the formatted transcript as utf8 encoded bytes
    """
    try:
        audio: ndarray = load_audio(audio_bytes)

        print("transcribing")
        transcription_result: TranscriptionResult = transcribe_audio(audio)
        # torch.cuda.empty_cache() # emptying cache avoids ooms at the cost of processing speed

        print("aligning")
        alignment_result: AlignmentResult = align_transcription(audio, transcription_result["segments"])
        # torch.cuda.empty_cache()

        print("diarizing")
        diarization_result: DiarizationResult = run_diarization(audio)
        # torch.cuda.empty_cache()

        print("post processing")
        transcript_bytes: bytes = postprocess_segments(diarization_result, alignment_result)
        return transcript_bytes
    except Exception as e: raise TranscriptionError(f"transcription with diarization failed: {e}") from e
