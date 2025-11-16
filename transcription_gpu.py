import os; import sys; import time
import logging; import warnings; import shutil
import contextlib; import argparse
import subprocess; import json
import whisperx; import torch
# from pydub import AudioSegment
from pathlib import Path
from typing import Optional, List, Dict, Any, Iterator
from lightning.pytorch.utilities import disable_possible_user_warnings

WordDict = Dict[str, Any] # type alias to hold arbitrary metadata for utterances
DEVICE: str = "cuda"
VERBOSE: bool = False

# for loading the pyannote diarization model
RAW_HF_TOKEN: Optional[str] = os.environ.get("HF_TOKEN")
if not RAW_HF_TOKEN:
    print("missing huggingface token. `set/export HF_TOKEN=token`")
    sys.exit(1)
HF_TOKEN: str = RAW_HF_TOKEN

if not torch.cuda.is_available():
    print("cuda is unavailable. https://developer.nvidia.com/cuda-downloads")
    sys.exit(1)

def check_ffmpeg():
    """
    ensures that ffmpeg is available on the path
    only gets called if a non-.wav file is passed for transcription
    """
    if not shutil.which("ffmpeg"):
        print("ffmpeg not found. https://ffmpeg.org/download.html")
        sys.exit(1)

def suppress_logs() -> None:
    """
    disables user warnings from lightning, filters out python warnings, and sets logging levels to error, unless verbose is passed
    """
    if VERBOSE: return
    disable_possible_user_warnings()
    warnings.filterwarnings("ignore")
    logging.getLogger("pyannote").setLevel(logging.ERROR)
    logging.getLogger("pytorch_lightning").setLevel(logging.ERROR)
    logging.getLogger("whisperx").setLevel(logging.ERROR)

@contextlib.contextmanager
def suppress_everything() -> Iterator[None]:
    """
    redirects stdout and stderr to /dev/null until the context exits, unless verbose is passed
    """
    if VERBOSE: yield; return
    with open(os.devnull, "w") as devnull:
        original_stdout = sys.stdout; original_stderr = sys.stderr
        try: sys.stdout = devnull; sys.stderr = devnull; yield
        finally: sys.stdout = original_stdout; sys.stderr = original_stderr

def format_timestamp(total_seconds: float) -> str:
    """
    converts a timestamp in seconds to hh:mm:ss (3661.3 to 01:01:01). fractional seconds are discarded
    """
    hours: int = int(total_seconds // 3600)
    minutes: int = int((total_seconds % 3600) // 60)
    seconds: int = int(total_seconds % 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"

def format_duration(seconds: float) -> str:
    """
    converts a duration in seconds to a readable string
    this is for reporting total processing time to the console
    """
    if seconds < 60: return f"{seconds:.1f} second{'s' if int(seconds) != 1 else ''}"
    seconds = int(seconds)
    minutes: int = int(seconds // 60)
    remaining_seconds: float = seconds % 60
    if minutes < 60: return f"{minutes} minute{'s' if minutes != 1 else ''} and {int(remaining_seconds)} seconds"
    hours: int = int(minutes // 60)
    minutes = minutes % 60
    return f"{hours} hour{'s' if hours != 1 else ''}, {minutes} minute{'s' if minutes != 1 else ''} and {int(remaining_seconds)} second{'s' if int(remaining_seconds) != 1 else ''}"

def convert_to_wav(input_path: Path) -> Path:
    """
    converts an audio file to a 16 kHz, 16.bit pcm wav using ffmpeg
    the output file shares the same base name as the input, but with a .wav extension
    whisperx requires .wav
    """
    check_ffmpeg()
    wav_output_path = input_path.with_suffix(".wav")
    if not input_path.is_file():
        print(f"'{input_path}' not found")
        sys.exit(1)
    ffmpeg_cmd = [
        "ffmpeg", "-y",         # overwrites any existing output file
        "-i", str(input_path),  # the file passed in params as source
        # "-ac", "1",
        "-ar", "16000",         # sample rate 16 kHz
        "-sample_fmt", "s16",   # sample format 16-bit signed
        "-c:a", "pcm_s16le",    # pcm_s16le codec
        str(wav_output_path),
    ]
    try:
        with suppress_everything(): ffmpeg_proc = subprocess.run(ffmpeg_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if ffmpeg_proc.returncode != 0: raise RuntimeError(ffmpeg_proc.stderr.decode(errors="ignore"))
        if VERBOSE: print(f"{input_path} converted to {wav_output_path}") # only informs user of conversion if verbose passed
        return wav_output_path
    except Exception as e:
        print(f"file conversion failed: {e}")
        sys.exit(1)

def transcribe_audio(audio_path: Path, model) -> WordDict: # after model ", device: str"
    """
    performs transcription on the given audio using a preloaded whisperx model
    uses torch.inference_mode() to disable gradient tracking for speed and lower memory usage

    returns a dictionary with the raw transcription output: segments is a list of segments, each including
    1. start and end timestamps, and 2. text string
    """     
    with suppress_everything():
        # whisper_model = whisperx.load_model(model_name, device, compute_type="float16")
        with torch.inference_mode(): result: WordDict = model.transcribe(str(audio_path), language="en", task="transcribe")
    return result

def align_transcription(segments, audio_path: Path) -> WordDict:
    """
    aligns raw whisperx segments with the audio at a finer time resolution via whisperx alignment model
    returns a dictionary with alignment results: ssegments is a list of segments from transcribe_audio() with refined timestamps
    """
    with suppress_everything():
        align_model, align_metadata = whisperx.load_align_model(language_code="en", device=DEVICE)
        alignment_result: WordDict = whisperx.align(segments, align_model, align_metadata, str(audio_path), DEVICE)
    return alignment_result

def run_diarization(audio_path: Path, hf_token: str):
    """
    runs speaker diarization on an audio file using the pyannote pipeline through whisperx
    returns an object describing contiguous time spans for each detected speaker
    """
    with suppress_everything():
        diarization_pipeline = whisperx.diarize.DiarizationPipeline(
            model_name='pyannote/speaker-diarization@2.1', # do NOT change
            use_auth_token=hf_token,
            device=DEVICE
        )
        try: diarization_pipeline.set_params({"clustering": {"threshold": 0.70}}) # lower is more sensitive => more speakers, try adjusting
        except Exception: print("clustering treshold didn't pass"); pass # i'm not sure whether this param is actually supported in the api
        diarization_result = diarization_pipeline(str(audio_path))
    return diarization_result

def postprocess_segments(alignment_result: WordDict, diarization_result, speaker_gap_threshold: float = 0.8) -> List[WordDict]:
    """
    combines aligned transcription segments with diarization output into coherent utterances, labeled with speakers. core logic

    alignment_result is a dictionary returned by align_transcription()
    diarization_result is speaker diarization output returned by run_diarization()
    speaker_gap_threshold is the max gap in seconds between two segments from the same speaker for them to be merged into a single utterance
        for example, if segments for the same speaker are separated by 0.5 seconds, they are merged; if separated by 1.2 seconds, they become separate utterances
    
    returns a list of utterances; each utterance is a dictionary with:
            1. start time in seconds, as a float
            2. end time in seconds, as a float
            3. string label for the speaker
            4. full merged text spoken by that speaker in the given interval

    steps:
    1. clean aligned segments:
        extract asegments from alignment_result
        for each segment
            strip whitespace from the text;
            skip segments where the text is empty after stripping;
            normalise start and end timestamps;
            ensure end > start before keeping the segment.
        the result is cleaned_segments

    2. normalise diarization segments:
        attempt to interpret diarization_result using different possible apis:
            preferred: itertracks(yield_label=true) for pyannote 2.x pipelines;
            fallback: iterrows() if diarization_result is a dataframe-like object;
            fallback: a plain dict with a "segments" key.
        in each case, produce a list of speaker_segments, where each entry is {"start": float, "end": float, "label": string}
        sort speaker_segments by (start, end)

    3. speaker assignment for each transcription segment:
        define helper function speaker_for_interval(start_time, end_time).
        for each aligned transcription segment:
            compute time overlap with each speaker segment;
            choose the speaker label with maximum overlap duration;
            if no overlap is found:
                use the midpoint of the transcription segment and find the speaker segment that covers that midpoint
                if still not found, return UNKNOWN

    4. label each transcription segment:
        for every cleaned segment, call speaker_for_interval() to determine its speaker
        build labeled_segments so that each has "start", "end", "speaker", "text"

    5. merge adjacent segments into utterances:
        iterate over labeled_segments in chronological order
        maintain a list of utterances
        for each segment:
            if utterances is not empty and
                the current segment has the same speaker as the last utterance, and
                the time gap between the end of the previous utterance and the start of the current segment is <= to the gap threshold passed in params,
            then:
                merge the current segment into the last utterance
                optionally insert a space between texts, according to punctuation rules
                update the end of the previous utterance to the end of the current segment
            otherwise start a new utterance with this segment
        the spacing logic before concatenation avoids double spaces, missing spaces between words, and extra spaces before punctuation

    returns a list of coherent and readable utterances
    """
    # extract aligned segments from the alighnment result
    aligned_segments: List[WordDict] = alignment_result.get("segments") or []

    # clean segments
    cleaned_segments: List[WordDict] = []
    for segment in aligned_segments:
        text: str = (segment.get("text") or "").strip()
        if not text: continue # skip if the segment is all whitespace
        start_time: float = float(segment.get("start", 0.0))
        end_time: float = float(segment.get("end", start_time))
        # only keep segments that have positive duration
        if end_time > start_time: cleaned_segments.append({"start": start_time, "end": end_time, "text": text})
    if not cleaned_segments: return [] # if there are no valid segments after cleaning

    # convert the result of diarization into a list of speaker segments
    speaker_segments: List[WordDict] = []
    try:
        # preferred api is pyannote's itertracks
        for time_span, _, speaker_label in diarization_result.itertracks(yield_label=True):
            speaker_segments.append({"start": float(time_span.start), "end": float(time_span.end), "label": str(speaker_label)})
    except Exception:
        # fallback if diarization_result behaves like a dataframe
        if hasattr(diarization_result, "iterrows"):
            for _, row in diarization_result.iterrows():
                speaker_segments.append({
                    "start": float(row["start"]),
                    "end": float(row["end"]),
                    "label": str(row.get("speaker", row.get("label", "UNKNOWN")))
                })
        # fallback, dictionary with a segments list
        elif isinstance(diarization_result, dict) and "segments" in diarization_result:
            for row in diarization_result["segments"]:
                speaker_segments.append({
                    "start": float(row.get("start", 0.0)),
                    "end": float(row.get("end", 0.0)),
                    "label": str(row.get("speaker") or row.get("label") or "UNKNOWN")
                })
    speaker_segments.sort(key=lambda span: (span["start"], span["end"])) # sort chronologically 

    def speaker_for_interval(start_time: float, end_time: float) -> str:
        """
        determines the most likely speaker label given a transcription interval

        steps:
        1. max overlap 
            iterate through all segments
            for each segment compute the overlap in seconds
            track the label with the maximum overlap
            if a label achieves any non-zero overlap, return that label

        2. midpoint
            if no overlapping speaker segment is found:
                compute the midpoint of the segment
                find the speaker segment that contains this midpoint
                if found, return that label

        3. fallback
            if no match is found at all return UNKNOWN
        """
        best_label: Optional[str]
        max_overlap_seconds: float
        best_label, max_overlap_seconds = None, 0.0
        for span in speaker_segments:  # TODO FIX THIS IS O(N*M)
            if span["end"] <= start_time: continue # skip segments that end before the given interval
            if span["start"] >= end_time: break # once the start of the span is after the given interval, no further overlaps are possible
            overlap_seconds: float = max(0.0, min(end_time, span["end"]) - max(start_time, span["start"]))
            if overlap_seconds > max_overlap_seconds: max_overlap_seconds, best_label = overlap_seconds, span["label"]
        if best_label is not None: return best_label
        # fallback to midpoint
        midpoint_second: float = 0.5 * (start_time + end_time) 
        for span in speaker_segments:
            if span["start"] <= midpoint_second < span["end"]: return span["label"]
            if span["start"] > midpoint_second: break
        return "UNKNOWN" # fallback to unkown

    # label each segment with a speaker
    labeled_segments: List[WordDict] = []
    for segment in cleaned_segments:
        speaker_label: str = speaker_for_interval(segment["start"], segment["end"])
        labeled_segments.append({"start": segment["start"], "end": segment["end"], "speaker": speaker_label, "text": segment["text"]})

    # merge consecutive segments from the same speaker into longer utterances
    utterances: List[WordDict] = []
    for segment in labeled_segments:
        if utterances and utterances[-1]["speaker"] == segment["speaker"] and (segment["start"] - utterances[-1]["end"]) <= speaker_gap_threshold:
            # current segment is close enough and has the same speaker as the last utterance => merge text and extend the end timestamp
            last_utterance: WordDict = utterances[-1]

            # if segment["text"] and segment["text"][0] in ".,!?;:%)]}": last_utterance["text"] += segment["text"]
            # else:
            #     if last_utterance["text"] and not last_utterance["text"].endswith(" "): last_utterance["text"] += " "
            #     last_utterance["text"] += segment["text"]
            # last_utterance["end"] = segment["end"]

            # decide whether to insert a space before appending the next segment:
            #   if the existing text already ends with whitespace or punctuation do not add a space
            #   if the new segment starts with punctuation do not add a space
            #   otherwise add a space
            next_segment = segment["text"] or ""
            if last_utterance["text"] and not last_utterance["text"].endswith((" ", "\n", "—", "-", "(", "[", "{", "“", "'")) and not (next_segment and next_segment[0] in ".,!?;:%)]}"):
                last_utterance["text"] += " "
            last_utterance["text"] += next_segment.lstrip()
            last_utterance["end"] = segment["end"]
            
        else: utterances.append(segment) # start a new utterance entry if no existing utterance to merge into or speaker/gap conditions not met

    return utterances

def transcribe_with_diarization(audio_path: Path, model, output_path: Path, output_format: str) -> None:
    """
    this basically just calls all the functions above to make the full transcription pipeline and write the result to disk
    also computes and prints the time the script took processing the file, i was using that to track how well the script was optimised
    any exception raised in the pipeline steps throws an error and exits the program
    """
    print(f"\nprocessing: {audio_path}")
    start_time: float = time.perf_counter()

    try:
        print("transcribing")
        transcription_result: WordDict = transcribe_audio(audio_path, model) # after model ", DEVICE"
        # torch.cuda.empty_cache() # emptying cache avoids ooms at the cost of processing speed

        print("aligning")
        alignment_result: WordDict = align_transcription(transcription_result["segments"], audio_path)
        # torch.cuda.empty_cache()

        print("diarizing")
        diarization_result = run_diarization(audio_path, HF_TOKEN)
        # torch.cuda.empty_cache()

        print("post processing")
        utterance_lines = postprocess_segments(alignment_result, diarization_result)

    except Exception as e: print(f"{e}"); sys.exit(1)

    end_time: float = time.perf_counter()
    if output_format == "json": file_body = json.dumps({"utterances": utterance_lines}, ensure_ascii=False, indent=2)
    else:
        formatted_lines = [f"[{format_timestamp(utterance_line['start'])}] {utterance_line['speaker']}: {utterance_line['text']}" for utterance_line in utterance_lines]
        file_body = "\n".join(formatted_lines)

    output_path.write_text(file_body, encoding="utf-8")
    print(f"saved to: {output_path}")
    print(f"\ntook {format_duration(end_time-start_time)}")

def overwrite(output_path: Path, overwrite_flag: bool) -> Path:
    """
    decides the filepath to use for the output file

    if overwriting is not permitted:
        if output path does not yet exist return output path
        if output_path already exists recursively add _new to the output path until doesn't yet exist
    """
    if not output_path.exists() or overwrite_flag: return output_path

    # response = input(f"'{output_path}' already exists. overwrite? [y/n]: ").strip().lower()
    # if response == "y": return output_path

    def bump(path: Path) -> Path:
        base = path.stem
        suffix = path.suffix
        new_base = base + "_new"
        candidate = path.with_name(new_base + suffix)

        if candidate.exists(): return bump(candidate)
        return candidate
    
    return bump(output_path)

def delete_wav(wav_path: Path):
    """
    deletes an intermediate .wav if it exists; doesn't exit if couldn't delete
    """
    if wav_path.exists():
        try: wav_path.unlink()
        except Exception as e: print(f"could not delete wav. {e}")

if __name__ == "__main__": # for cmd
    # total_start_time: float = time.perf_counter()
    parser = argparse.ArgumentParser()
    parser.add_argument("input_file")
    parser.add_argument("--model", default="medium") # can specify a different whisperx model
    parser.add_argument("-v", "--verbose", action="store_true") # doesn't supress any logs for debugging
    parser.add_argument("-k", "--keep-wav", action="store_true") # doesn't delete intermediate .wav
    parser.add_argument('-o', '--overwrite', action='store_true') # overwrites any existing outputs
    parser.add_argument('-f', '--out_format', choices=['txt','json'], default='txt') # deprecate? idk if i will actually ever need .json outputs
    args = parser.parse_args()

    VERBOSE = args.verbose
    suppress_logs()

    # resolve and validate the input path
    input_path = Path(args.input_file)
    if not input_path.is_file():
        print(f"{input_path} does not exist")
        sys.exit(1)

    # decide whether conversion to .wav is necessary
    extension = input_path.suffix.lower()
    if extension == ".wav": wav_path = input_path;  wav_converted = False
    else: wav_path = convert_to_wav(input_path);    wav_converted = True

    # determine output filename
    base_stem = wav_path.stem
    ext = ".json" if args.out_format == "json" else ".txt"
    output_path = Path(f"{base_stem}{ext}")
    output_path = overwrite(output_path, args.overwrite)

    # load whisperx model
    whisper_model = None
    if args.model != parser.get_default("model"):
        try:
            with suppress_everything(): whisper_model = whisperx.load_model(args.model, DEVICE, compute_type="float16")
            # torch.cuda.empty_cache()
        except Exception as e: print(f"model '{args.model}' failed to load. {e}"); sys.exit(1) # if user requested a model that cannot be loaded
    else:
        try:
            with suppress_everything(): whisper_model = whisperx.load_model("medium", DEVICE, compute_type="float16")
            # torch.cuda.empty_cache()
        except Exception as e: print(f"model '{args.model}' failed to load. {e}"); sys.exit(1) # this should genuinely never happen

    # do the thing!
    try: transcribe_with_diarization(wav_path, whisper_model, output_path, args.out_format)
    finally: 
        # total_end_time: float = time.perf_counter()
        # print(f"\ntotal {format_duration(total_end_time-total_start_time)}")
        if wav_converted and not args.keep_wav: delete_wav(wav_path)
