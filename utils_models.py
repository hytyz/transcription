import os; import torch; import whisperx
from typing import Optional, Dict
from whisperx.asr import FasterWhisperPipeline
from whisperx.diarize import DiarizationPipeline
from utils_types import TranscriptionError, AlignMetadata

_DEVICE: str = "cuda" # required for diarization on gpu
_ALIGN_MODEL: torch.nn.Module # cached whisperx alignment model instance, created on first use by _get_align_model
_ALIGN_METADATA: AlignMetadata # cached metadata of the alignment model
_DIARIZATION_PIPELINE: DiarizationPipeline # cached diarization pipeline instance, created on first use by _get_diarization_pipeline
_WHISPER_MODELS: Dict[str, FasterWhisperPipeline] = {} # cached dictionary of model names and already loaded whisperx pipelines

# for loading the pyannote diarization model
_token: Optional[str] = os.environ.get("HF_TOKEN")
if _token is None or _token.strip() == "": raise TranscriptionError("hf_token is not set")
__HF_TOKEN: str = _token
if not torch.cuda.is_available(): raise TranscriptionError("cuda is unavailable. https://developer.nvidia.com/cuda-downloads")

def get_device() -> str: return _DEVICE

def _get_align_model():
    """
    loads and caches the whisperx alignment model and metadata
    subsequent calls reuse the cached objects instead of reloading the model
    """
    global _ALIGN_MODEL, _ALIGN_METADATA
    if _ALIGN_MODEL is None or _ALIGN_METADATA is None: 
        _ALIGN_MODEL, _ALIGN_METADATA = whisperx.load_align_model(language_code="en", device=_DEVICE)
    return _ALIGN_MODEL, _ALIGN_METADATA


def _get_diarization_pipeline(speaker_threshold: float) -> DiarizationPipeline:
    """
    loads and caches the pyannote diarization pipeline used by whisperx
    subsequent calls reuse the cached pipeline instance
    """
    global _DIARIZATION_PIPELINE
    if _DIARIZATION_PIPELINE is None:
        # TODO find the actual github repo and cite it
        _DIARIZATION_PIPELINE = whisperx.diarize.DiarizationPipeline(model_name="pyannote/speaker-diarization@2.1", use_auth_token=__HF_TOKEN, device=DEVICE) # DO NOT CHANGE THIS
        try: _DIARIZATION_PIPELINE.set_params({"clustering": {"threshold": speaker_threshold}}) 
        except Exception as e: pass
    return _DIARIZATION_PIPELINE

def _load_whisper_model(model_name: str = "large") -> FasterWhisperPipeline:
    """
    loads and caches a whisperx model by name
    subsequent calls with the same model name reuse the cached pipeline instance
    tries float16 first and falls back to float32 when float16 is not supported
    """
    if model_name in _WHISPER_MODELS: return _WHISPER_MODELS[model_name]
    try: model: FasterWhisperPipeline = whisperx.load_model(model_name, _DEVICE, compute_type="float16")
    except ValueError as e:
        message = str(e).lower()
        if "float16" in message: model = whisperx.load_model(model_name, _DEVICE, compute_type="float32")
        else: raise TranscriptionError(f"model '{model_name}' failed to load: {e}") from e
    except Exception as e: raise TranscriptionError(f"model '{model_name}' failed to load: {e}") from e
    _WHISPER_MODELS[model_name] = model
    return model