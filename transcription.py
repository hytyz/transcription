from utils_types import *; import time; from pathlib import Path; from typing import List

def transcribe_with_diarization(audio_path: Path, model: FasterWhisperPipeline, output_path: Path, speaker_threshold: int) -> None:
    """
    this basically just calls all the functions above to make the full transcription pipeline and write the result to disk
    also computes and prints the time the script took processing the file, i was using that to track how well the script was optimised
    """
    print(f"\nprocessing: {audio_path}")
    start_time: float = time.perf_counter()

    try:
        print("transcribing")
        transcription_result: TranscriptionResult = transcribe_audio(audio_path, model)
        # torch.cuda.empty_cache() # emptying cache avoids ooms at the cost of processing speed

        print("aligning")
        alignment_result: AlignmentResult = align_transcription(transcription_result["segments"], audio_path)
        # torch.cuda.empty_cache()

        print("diarizing")
        diarization_result: DiarizationResult = run_diarization(audio_path, speaker_threshold)
        # torch.cuda.empty_cache()

        print("post processing")
        alignment_result = whisperx.assign_word_speakers(diarization_result, alignment_result)
        _fill_missing_word_speakers(alignment_result, diarization_result)
        utterances = postprocess_segments(alignment_result)

    except Exception as e: raise TranscriptionError(f"transcription with diarization failed: {e}") from e

    end_time: float = time.perf_counter()
    # formats the output of the utterances list into "[hh:mm:ss] speaker_xx: text" 
    formatted_lines: List[str] = [f"[{format_timestamp(utterance_line.start)}] {utterance_line.speaker}: {utterance_line.text}" for utterance_line in utterances]
    file_body: str = "\n".join(formatted_lines)

    output_path.write_text(file_body, encoding="utf-8")
    print(f"saved to: {output_path}")
    print(f"\ntook {format_duration(end_time-start_time)}")
