import os; import torch; import whisperx
from typing import cast
from whisperx.asr import FasterWhisperPipeline
from whisperx.diarize import DiarizationPipeline
from .dataclasses import TranscriptionError, AlignMetadata, align_metadata_from_whisper
from .asr_options import asr_options

# determines the n of speakers and how often segments are merged or split across speakers
DIARIZATION_CLUSTER_THRESHOLD = os.environ.get("DIARIZATION_THRESHOLD", "").strip() # empty = whatever the model ships with, lower it if speakers get merged
_DEVICE = "cuda" # required for diarization on gpu
_WHISPER_MODEL_NAME = os.environ.get("WHISPER_MODEL", "large-v3-turbo")
_DIARIZATION_MODEL_NAME = os.environ.get("DIARIZATION_MODEL", "pyannote/speaker-diarization-community-1")
_ALIGN_MODEL: torch.nn.Module | None = None
_ALIGN_METADATA: AlignMetadata | None = None
_DIARIZATION_PIPELINE: DiarizationPipeline | None = None
_WHISPER_MODEL: FasterWhisperPipeline | None = None

# for loading the pyannote diarization model
_token = os.environ.get("HF_TOKEN")
if _token is None or _token.strip() == "": raise TranscriptionError("hf_token is not set")
_HF_TOKEN = _token
if not torch.cuda.is_available(): raise TranscriptionError("cuda is unavailable. https://developer.nvidia.com/cuda-downloads")

def get_device(): return _DEVICE

def get_whisper_model():
    global _WHISPER_MODEL
    if _WHISPER_MODEL is not None: return _WHISPER_MODEL
    model_name = _WHISPER_MODEL_NAME

    try: model = whisperx.load_model(model_name, _DEVICE, compute_type="float16", asr_options=asr_options)
    except ValueError as e:
        message = str(e).lower()
        if "float16" in message: model = whisperx.load_model(model_name, _DEVICE, compute_type="float32", asr_options=asr_options)
        else: raise Exception(f"failed to load model '{model_name}': {e}") from e
    except TranscriptionError as e: raise TranscriptionError(f"failed to load model '{model_name}': {e}") from e
    except Exception as e: raise Exception(f"model '{model_name}' failed to load: {e}") from e

    _WHISPER_MODEL = model
    return model

def get_align_model() -> tuple[torch.nn.Module, AlignMetadata]:
    global _ALIGN_MODEL, _ALIGN_METADATA
    if _ALIGN_MODEL is None or _ALIGN_METADATA is None:
        model, meta = whisperx.load_align_model(language_code="en", device=_DEVICE)
        _ALIGN_MODEL = model
        _ALIGN_METADATA = align_metadata_from_whisper(meta)
    return cast(torch.nn.Module, _ALIGN_MODEL), cast(AlignMetadata, _ALIGN_METADATA)

def get_diarization_pipeline():
    global _DIARIZATION_PIPELINE
    if _DIARIZATION_PIPELINE is None:
        # whisperx 3.8 renamed use_auth_token to token, and 3.8.5 still had use_auth_token left in places (whisperX#1406)
        try: _DIARIZATION_PIPELINE = DiarizationPipeline(model_name=_DIARIZATION_MODEL_NAME, token=_HF_TOKEN, device=_DEVICE)
        except TypeError: _DIARIZATION_PIPELINE = DiarizationPipeline(model_name=_DIARIZATION_MODEL_NAME, use_auth_token=_HF_TOKEN, device=_DEVICE)
        if DIARIZATION_CLUSTER_THRESHOLD:
            try: _DIARIZATION_PIPELINE.model.instantiate({"clustering": {"threshold": float(DIARIZATION_CLUSTER_THRESHOLD)}})
            except Exception as e: print(f"did not set diarization clustering threshold: {e}")
    return cast(DiarizationPipeline, _DIARIZATION_PIPELINE)
