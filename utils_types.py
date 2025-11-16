from dataclasses import dataclass
from typing import Any, List, Mapping, TypedDict, Dict, Union, NamedTuple
from pandas import DataFrame
from pyannote.core import Annotation

#internal data structures

@dataclass
class Segment:
    """
    segment after transcription or alignment, without speaker labels
    """
    start: float
    end: float
    text: str

@dataclass
class SpeakerSegment:
    """
    diarization segment, without text
    """
    start: float
    end: float
    label: str

@dataclass
class Utterance:
    """
    final utterance after merging text and speakers
    """
    start: float
    end: float
    speaker: str
    text: str

class TranscriptionError(Exception): 
    """
    raised when any step of the transcription, alignment, or diarization pipeline fails
    """
    pass

# external api views
class SegmentDict(TypedDict):
    """
    raw segment from whisperx transcription or alignment
    """
    start: float
    end: float
    text: str

class TranscriptionResult(TypedDict):
    """
    output of the transcription step from whisperx

    segments is the list of raw segments produced by the whisperx model before alignment
    """
    segments: List[SegmentDict]

class AlignmentResult(TypedDict):
    """
    output of the alignment step from whisperx
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

class WordEntry(TypedDict):
    """
    word-level entry attached to aligned segments from whisperx
    """
    start: float
    end: float
    word: str
    speaker: object | None

# diarization output type used throughout
DiarizationResult = Union[Annotation, DataFrame, DiarizationDict]

class Track(NamedTuple):
    """
    diarization tuple yielded by Annotation.itertracks() from pyannote
    https://pyannote.github.io/pyannote-core/reference.html#pyannote.core.Annotation.itertracks
    """
    time_span: Any
    track_id: Any
    speaker_label: Any

class Row(NamedTuple):
    """
    diarization tuple yielded by DataFrame.iterrows() from pandas
    https://pandas.pydata.org/docs/reference/api/pandas.DataFrame.iterrows.html
    """
    index: Any
    values: Mapping[str, Any]
