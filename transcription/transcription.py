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

import argparse
from pathlib import Path

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("audio_path")
    args = parser.parse_args()

    input_path = Path(args.audio_path)
    output_path = input_path.with_suffix(".txt")

    with input_path.open("rb") as f: audio_bytes = f.read()

    transcript_bytes = generate_diarized_transcript(audio_bytes)
    transcript_text = transcript_bytes.decode("utf-8")

    with output_path.open("w", encoding="utf-8") as f: f.write(transcript_text)


if __name__ == "__main__":
    main()