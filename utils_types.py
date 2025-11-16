from dataclasses import dataclass
from typing import Any, List, Mapping, TypedDict, Dict, Union, NamedTuple
from pandas import DataFrame
from pyannote.core import Annotation

# internal objects
@dataclass
class Segment:
    """
    output of transcription or alignment, no speaker
    """
    start: float
    end: float
    text: str

@dataclass
class SpeakerSegment:
    """
    output of diarization, no text
    """
    start: float
    end: float
    label: str

@dataclass
class Utterance:
    """
    text from segment + label from SpeakerSegment with adjusted intervals from the first and last word
    """
    start: float
    end: float
    speaker: str
    text: str

# external api views returned by whisperx
class SegmentDict(TypedDict):
    """
    raw segment from transcription or alignment
    """
    start: float
    end: float
    text: str

class TranscriptionResult(TypedDict):
    """
    output of the transcription step

    segments is the list of raw segments produced by the whisperx model before alignment
    """
    segments: List[SegmentDict]

class AlignmentResult(TypedDict):
    """
    output of the alignment step
    segments is the list of segments from TranscriptionResult
    """
    segments: List[SegmentDict]

class DiarizationSegmentDict(TypedDict, total=False):
    """
    a single diarization segment
    """
    start: float
    end: float
    speaker: str
    label: str

class DiarizationDict(TypedDict):
    """
    diarization output that exposes a segments collection
    """
    segments: List[DiarizationSegmentDict]

class AlignMetadata(TypedDict):
    """
    metadata describing the alignment model returned by whisperx.load_align_model
    """
    language: str
    dictionary: Dict[str, int]
    type: str

# diarization output type used throughout
DiarizationResult = Union[Annotation, DataFrame, DiarizationDict]

class TranscriptionError(Exception): pass

# diarization tuple yielded by itertracks() from pyannote # https://pyannote.github.io/pyannote-core/reference.html#pyannote.core.Annotation.itertracks
class Track(NamedTuple):
    time_span: Any
    track_id: Any
    speaker_label: Any

# diarization tuple yielded by iterrows() from pandas # https://pandas.pydata.org/docs/reference/api/pandas.DataFrame.iterrows.html
class Row(NamedTuple):
    index: Any
    values: Mapping[str, Any]

