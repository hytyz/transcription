import os; import torch; import whisperx
from typing import cast
from whisperx.asr import FasterWhisperPipeline
from whisperx.diarize import DiarizationPipeline
from utils_types import TranscriptionError, AlignMetadata

# determines the n of speakers and how often segments are merged or split across speakers
DIARIZATION_CLUSTER_THRESHOLD: float = 0.6 # try lowering to reduce overmerging
_DEVICE: str = "cuda" # required for diarization on gpu
_ALIGN_MODEL: torch.nn.Module | None = None # cached whisperx alignment model instance
_ALIGN_METADATA: AlignMetadata | None = None # cached metadata of the alignment model
_DIARIZATION_PIPELINE: DiarizationPipeline | None = None # cached diarization pipeline instance
_WHISPER_MODEL: FasterWhisperPipeline | None = None # cached whisperx transcription model instance

# for loading the pyannote diarization model
_token: str | None = os.environ.get("HF_TOKEN")
if _token is None or _token.strip() == "": raise TranscriptionError("hf_token is not set")
_HF_TOKEN: str = _token
if not torch.cuda.is_available(): raise TranscriptionError("cuda is unavailable. https://developer.nvidia.com/cuda-downloads")

def get_device() -> str: return _DEVICE

def get_whisper_model() -> FasterWhisperPipeline:
    """loads and caches the whisperx large model"""
    global _WHISPER_MODEL
    if _WHISPER_MODEL is not None: return _WHISPER_MODEL
    model_name: str = "large"

    try: model: FasterWhisperPipeline = whisperx.load_model(model_name, _DEVICE, compute_type="float16")
    except ValueError as e:
        message = str(e).lower()
        if "float16" in message: model = whisperx.load_model(model_name, _DEVICE, compute_type="float32")
        else: raise Exception(f"failed to load model '{model_name}': {e}") from e
    except TranscriptionError as e: raise TranscriptionError(f"failed to load model '{model_name}': {e}") from e
    except Exception as e: raise Exception(f"model '{model_name}' failed to load: {e}") from e

    _WHISPER_MODEL = model
    print("got whisper model")
    return model

def get_align_model() -> tuple[torch.nn.Module, AlignMetadata]:
    """loads and caches the whisperx alignment model and its metadata"""
    global _ALIGN_MODEL, _ALIGN_METADATA
    if _ALIGN_MODEL is None or _ALIGN_METADATA is None: 
        _ALIGN_MODEL, _ALIGN_METADATA = whisperx.load_align_model(language_code="en", device=_DEVICE)
    print("got align model")
    return cast(torch.nn.Module, _ALIGN_MODEL), cast(AlignMetadata, _ALIGN_METADATA)

def get_diarization_pipeline() -> DiarizationPipeline:
    """loads and caches the pyannote diarization pipeline used by whisperx"""
    global _DIARIZATION_PIPELINE
    if _DIARIZATION_PIPELINE is None:
        # https://github.com/m-bain/whisperX/issues/499 -- do NOT switch from the 2.1 model
        _DIARIZATION_PIPELINE = DiarizationPipeline(model_name="pyannote/speaker-diarization@2.1", use_auth_token=_HF_TOKEN, device=_DEVICE)
        try: _DIARIZATION_PIPELINE.set_params({"clustering": {"threshold": DIARIZATION_CLUSTER_THRESHOLD}}) 
        except Exception as e: pass
    print("got dia model")
    return cast(DiarizationPipeline, _DIARIZATION_PIPELINE)
