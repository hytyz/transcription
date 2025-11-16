import sys
import argparse; import shutil
import subprocess; import math
import ffmpeg; import numpy
import whisperx; import torch; import re
# from pydub import AudioSegment
from pathlib import Path
from whisperx.asr import FasterWhisperPipeline
from typing import Optional, List, Any, Iterable, Callable, Mapping, Pattern, Tuple

from utils_types import *







    # old code
    parser = argparse.ArgumentParser()
    parser.add_argument("input_file")
    parser.add_argument("--model", default="large")             # can specify a different whisperx model
    parser.add_argument("-t", "--threshold", default="0.7")     # the smallest gap between utterances, lower = more sensitive
    parser.add_argument("-v", "--verbose", action="store_true") # enables all logs for debugging
    args = parser.parse_args()

        # TODO move to models.py
        # load whisperx model
        try:
            whisper_model: FasterWhisperPipeline = whisperx.load_model(args.model, DEVICE, compute_type="float16")
        except ValueError as e:
            message = str(e).lower()
            if "float16" in message: whisper_model: FasterWhisperPipeline = whisperx.load_model(args.model, DEVICE, compute_type="float32")
            else: raise TranscriptionError(f"model '{args.model}' failed to load: {e}") from e
        except Exception as e: raise TranscriptionError(f"model '{args.model}' failed to load: {e}") from e

        # do the thing!
        transcribe_with_diarization(wav_path, whisper_model, output_path, args.threshold)