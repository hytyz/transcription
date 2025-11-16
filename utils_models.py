import os; import torch; import whisperx
from typing import Optional, cast
from whisperx.asr import FasterWhisperPipeline
from whisperx.diarize import DiarizationPipeline
from utils_types import TranscriptionError, AlignMetadata

# determines the n of speakers and how often segments are merged or split across speakers
DIARIZATION_CLUSTER_THRESHOLD: float = 0.6 # try lowering to reduce overmerging
_DEVICE: str = "cuda" # required for diarization on gpu
_ALIGN_MODEL: Optional[torch.nn.Module] = None # cached whisperx alignment model instance
_ALIGN_METADATA: Optional[AlignMetadata] = None # cached metadata of the alignment model
_DIARIZATION_PIPELINE: Optional[DiarizationPipeline] = None # cached diarization pipeline instance
_WHISPER_MODEL: Optional[FasterWhisperPipeline] = None # cached whisperx transcription model instance

# for loading the pyannote diarization model
_token: Optional[str] = os.environ.get("HF_TOKEN")
if _token is None or _token.strip() == "": raise TranscriptionError("hf_token is not set")
__HF_TOKEN: str = _token
if not torch.cuda.is_available(): raise TranscriptionError("cuda is unavailable. https://developer.nvidia.com/cuda-downloads")

def get_device() -> str: return _DEVICE

def get_whisper_model() -> FasterWhisperPipeline:
    """
    loads and caches the whisperx large model on the configured device
    tries float16 first and falls back to float32 when float16 is not supported
    """
    global _WHISPER_MODEL
    if _WHISPER_MODEL is not None: return _WHISPER_MODEL
    model_name: str = "large"

    try: model: FasterWhisperPipeline = whisperx.load_model(model_name, _DEVICE, compute_type="float16")
    except ValueError as e:
        message = str(e).lower()
        if "float16" in message: model = whisperx.load_model(model_name, _DEVICE, compute_type="float32")
        else: raise
    except TranscriptionError: raise
    except Exception as e: raise Exception(f"model '{model_name}' failed to load: {e}") from e

    _WHISPER_MODEL = model
    return model

def get_align_model() -> tuple[torch.nn.Module, AlignMetadata]:
    """
    loads and caches the whisperx alignment model and metadata
    subsequent calls reuse the cached objects instead of reloading the model
    """
    global _ALIGN_MODEL, _ALIGN_METADATA
    if _ALIGN_MODEL is None or _ALIGN_METADATA is None: 
        _ALIGN_MODEL, _ALIGN_METADATA = whisperx.load_align_model(language_code="en", device=_DEVICE)
    return cast(torch.nn.Module, _ALIGN_MODEL), cast(AlignMetadata, _ALIGN_METADATA)

def get_diarization_pipeline() -> DiarizationPipeline:
    """
    loads and caches the pyannote diarization pipeline used by whisperx
    subsequent calls reuse the cached pipeline instance
    """
    global _DIARIZATION_PIPELINE
    if _DIARIZATION_PIPELINE is None:
        # https://github.com/m-bain/whisperX/issues/499 -- do NOT switch from the 2.1 model
        _DIARIZATION_PIPELINE = DiarizationPipeline(model_name="pyannote/speaker-diarization@2.1", use_auth_token=__HF_TOKEN, device=_DEVICE)
        try: _DIARIZATION_PIPELINE.set_params({"clustering": {"threshold": DIARIZATION_CLUSTER_THRESHOLD}}) # type: ignore[attr-defined]
        except Exception: pass
    return cast(DiarizationPipeline, _DIARIZATION_PIPELINE)
