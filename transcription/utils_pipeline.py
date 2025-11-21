import ffmpeg; import torch; import whisperx
from numpy import ndarray, frombuffer, clip, dtype
from shutil import which
import tempfile
import subprocess
from pandas import DataFrame
from whisperx.asr import FasterWhisperPipeline
from utils_types import TranscriptionError, TranscriptionResult, SegmentDict, AlignmentResult, DiarizationSegmentDict
from utils_models import get_align_model, get_diarization_pipeline, get_device, get_whisper_model

DEVICE: str = get_device()
STATES: tuple[str, str, str, str, str, str] = ("idle", "received", "transcribing", "aligning", "diarizing", "post-processing")
_FFMPEG_AVAILABLE: bool = which("ffmpeg") is not None # caching ffmpeg presence so that it's not called repeatedly

def convert_to_wav(audio_bytes: bytes) -> bytes:
    """Convert any audio format to mono wav begdrugingly using subprocess and ffmpeg."""
    try:
        process = subprocess.Popen(
            [
                "ffmpeg", "-y",
                "-i", "pipe:0",      # input from STDIN
                "-ac", "1",          # mono
                "-ar", "16000",      # 16kHz
                "-f", "wav",         # output format
                "pipe:1",            # output to STDOUT
            ],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,)
        out, err = process.communicate(input=audio_bytes)
        if process.returncode != 0:
            raise RuntimeError(f"FFmpeg conversion failed: {err.decode()}")
        return out
    except Exception as e:
        print("FFmpeg error:", e)
        raise

def load_audio(data:bytes) -> ndarray:
    """
    creates a temporary file from the input, decodes it into a mono 16 khz float32 waveform via ffmpeg
    returns a 1d numpy array with samples normalised to [-1.0, 1.0] per whisperx's wants
    """
    if not _FFMPEG_AVAILABLE: raise TranscriptionError("ffmpeg not found. https://ffmpeg.org/download.html")

    # .m4a is in the mp4 family. to parse mp4 containers, parser would need random access to 
    # get the moov atom (the index and timing info), which is placed at the end of mp4 containers
    # when the input is a nonseekable pipe (stdin), ffmpeg can only consume bytes in order, 
    # so in m4a files it doesn't see the moov atom and treats the input as a partial (=unusable) file. 
    # a (temporary) file is seekable and is the only viable, afaik, solution    
    with tempfile.NamedTemporaryFile(suffix=".audio") as temporary_file:
        # this is saved in /tmp
        temporary_file.write(data)
        # ensure the new file is out of the buffer so ffmpeg doesn't think the file is partial
        temporary_file.flush() 

        ffmpeg_cmd = [
            "ffmpeg",
            "-nostdin", # disables standard input
            "-loglevel", "error", # only spew out errors
            "-i", temporary_file.name,
            "-ac", "1", # not sure whether setting it to mono actually improves anything
            "-ar", "16000", # sample rate 16 kHz
            "-f", "f32le", # output format pcm 32 bit float little-endian
            "pipe:1", 
        ]

        process = subprocess.run(ffmpeg_cmd, input=data, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if process.returncode != 0: raise TranscriptionError(process.stderr.decode(errors="ignore"))
        
        if not process.stdout: raise RuntimeError("decoded audio is empty")
        audio = frombuffer(process.stdout, dtype=dtype("<f4"))
        return clip(audio, -1.0, 1.0)

def transcribe_audio(audio: ndarray) -> TranscriptionResult:
    """run transcription on audio and return raw segments via cached whisperx model"""
    whisper_model: FasterWhisperPipeline = get_whisper_model()
    with torch.inference_mode(): result: TranscriptionResult = whisper_model.transcribe(audio, language="en", task="transcribe") 
    return result

def align_transcript_segments(audio: ndarray, segments: list[SegmentDict]) -> AlignmentResult:
    """aligns raw whisperx segments to audio via the cached alignment model"""
    align_model, align_metadata = get_align_model()
    alignment_result: AlignmentResult = whisperx.align(segments, align_model, align_metadata, audio, DEVICE)
    return alignment_result

def run_diarization_pipeline(audio: ndarray) -> DataFrame:
    """runs speaker diarization on audio via the cached diarization pipeline"""
    diarization_pipeline = get_diarization_pipeline()
    diarization_result: DataFrame = diarization_pipeline(audio, min_speakers=2, max_speakers=5)
    return diarization_result

def postprocess_segments(diarization_result: DataFrame, alignment_result: AlignmentResult) -> bytes:
    """merges word level speakers and timings into final utterances and formats the transcript"""
    alignment_result = whisperx.assign_word_speakers(diarization_result, alignment_result)
    _fill_missing_word_speakers(alignment_result, diarization_result)

    lines: list[str] = []
    for segment in alignment_result.get("segments", []):
        words = [w for w in segment.get("words", []) if isinstance(w, dict) and isinstance(w.get("word"), str)]
        if not words: continue
        start = float(words[0].get("start") or 0.0)
        speaker = str(words[0].get("speaker") or "UNKNOWN")
        text = " ".join(w["word"] for w in words)
        lines.append(f"[{_format_timestamp(start)}] {speaker}: {text}")

    return "\n".join(lines).encode("utf-8")


def _fill_missing_word_speakers(alignment_result: AlignmentResult, diarization_result: DataFrame) -> None:
    """fills missing word "speaker" fields in alignment_result using diarization turns"""
    # TODO WRITE COMMENTS FOR THIS THING
    diarization_intervals: DiarizationSegmentDict = []
    for _, diarization_row in diarization_result.iterrows():
        if "start" in diarization_row and "end" in diarization_row:
            diarization_intervals.append(
                DiarizationSegmentDict( # TODO do this everywhere
                (float(diarization_row["start"]), float(diarization_row["end"]), 
                 str(diarization_row.get("speaker") or diarization_row.get("label") or ""))))

    for segment in alignment_result.get("segments", []):
        for word_entry in segment.get("words", []):
            if word_entry.get("speaker"): continue
            word_start = word_entry.get("start")
            if word_start is None: continue
            word_time = float(word_start)
            for interval_start, interval_end, interval_label in diarization_intervals:
                if interval_start <= word_time < interval_end and interval_label:
                    word_entry["speaker"] = interval_label
                    break

def _format_timestamp(total_seconds: float) -> str:
    hours: int = int(total_seconds // 3600)
    minutes: int = int((total_seconds % 3600) // 60)
    seconds: int = int(total_seconds % 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    