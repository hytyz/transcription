from numpy import ndarray
from pandas import DataFrame
from module.dataclasses import TranscriptionError, TranscriptionResult, AlignmentResult
from module.pipeline import load_audio, transcribe_audio, align_transcript_segments, run_diarization_pipeline, postprocess_segments
from typing import Callable

def generate_diarized_transcript(audio_bytes: bytes, on_status: Callable[[str], None] | None = None) -> bytes:
    """runs transcription, alignment, diarization, and formatting for a single audio blob"""
    try:
        if on_status: on_status("received")
        audio: ndarray = load_audio(audio_bytes)
        if on_status: on_status("transcribing")
        transcription_result: TranscriptionResult = transcribe_audio(audio)
        if on_status: on_status("aligning")
        alignment_result: AlignmentResult = align_transcript_segments(audio, transcription_result.segments)
        if on_status: on_status("diarizing")
        diarization_result: DataFrame = run_diarization_pipeline(audio)
        if on_status: on_status("postprocessing")
        transcript_bytes: bytes = postprocess_segments(diarization_result, alignment_result)
        return transcript_bytes
    except TranscriptionError as e: raise TranscriptionError(f"transcription with diarization failed: {e}") from e
    except Exception as e: raise Exception(f"transcription with diarization failed: {e}") from e

# this is temporary for cli testing

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

__all__ = ["generate_diarized_transcript", "main"]

if __name__ == "__main__":
    main()