import os; import torch; import whisperx
from typing import cast, Final
from whisperx.asr import FasterWhisperPipeline
from whisperx.diarize import DiarizationPipeline
from .dataclasses import TranscriptionError, AlignMetadata, align_metadata_from_whisper
from transcription.module.asr_options import asr_options

# determines the n of speakers and how often segments are merged or split across speakers
DIARIZATION_CLUSTER_THRESHOLD: Final[float] = 0.5 # try lowering to reduce overmerging
_DEVICE: Final[str] = "cuda" # required for diarization on gpu
_ALIGN_MODEL: torch.nn.Module | None = None
_ALIGN_METADATA: AlignMetadata | None = None
_DIARIZATION_PIPELINE: DiarizationPipeline | None = None
_WHISPER_MODEL: FasterWhisperPipeline | None = None

# for loading the pyannote diarization model
_token: str | None = os.environ.get("HF_TOKEN")
if _token is None or _token.strip() == "": raise TranscriptionError("hf_token is not set")
_HF_TOKEN: Final[str] = _token
if not torch.cuda.is_available(): raise TranscriptionError("cuda is unavailable. https://developer.nvidia.com/cuda-downloads")

def get_device() -> str: return _DEVICE

def get_whisper_model() -> FasterWhisperPipeline:
    """loads and caches the whisperx large model"""
    global _WHISPER_MODEL
    if _WHISPER_MODEL is not None: return _WHISPER_MODEL
    model_name: str = "large"

    try: model: FasterWhisperPipeline = whisperx.load_model(model_name, _DEVICE, compute_type="float16", asr_options=asr_options)
    except ValueError as e:
        message = str(e).lower()
        if "float16" in message: model = whisperx.load_model(model_name, _DEVICE, compute_type="float32")
        else: raise Exception(f"failed to load model '{model_name}': {e}") from e
    except TranscriptionError as e: raise TranscriptionError(f"failed to load model '{model_name}': {e}") from e
    except Exception as e: raise Exception(f"model '{model_name}' failed to load: {e}") from e

    _WHISPER_MODEL = model
    return model

def get_align_model() -> tuple[torch.nn.Module, AlignMetadata]:
    """loads and caches the whisperx alignment model and its metadata"""
    global _ALIGN_MODEL, _ALIGN_METADATA
    if _ALIGN_MODEL is None or _ALIGN_METADATA is None:
        model, meta = whisperx.load_align_model(language_code="en", device=_DEVICE)
        _ALIGN_MODEL = model
        _ALIGN_METADATA = align_metadata_from_whisper(meta)
    return cast(torch.nn.Module, _ALIGN_MODEL), cast(AlignMetadata, _ALIGN_METADATA)

def get_diarization_pipeline() -> DiarizationPipeline:
    """loads and caches the pyannote diarization pipeline used by whisperx"""
    global _DIARIZATION_PIPELINE
    if _DIARIZATION_PIPELINE is None:
        # https://github.com/m-bain/whisperX/issues/499 -- do NOT switch from the 2.1 model
        _DIARIZATION_PIPELINE = DiarizationPipeline(model_name="pyannote/speaker-diarization@2.1", use_auth_token=_HF_TOKEN, device=_DEVICE)
        try:
            _DIARIZATION_PIPELINE.set_params({"clustering": {"threshold": DIARIZATION_CLUSTER_THRESHOLD}})
        except Exception as e:
            print(f"did not set diarization clustering threshold: {e}")
    return cast(DiarizationPipeline, _DIARIZATION_PIPELINE)
