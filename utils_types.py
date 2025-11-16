from dataclasses import dataclass
from typing import List, TypedDict, Dict

#internal data structures

@dataclass
class SpeakerSegment:
    """diarization segment, without text"""
    start: float
    end: float
    label: str

@dataclass
class Utterance:
    """final utterance after merging text and speakers"""
    start: float
    end: float
    speaker: str
    text: str

class TranscriptionError(Exception): pass

# external api views
class SegmentDict(TypedDict):
    """raw segment from whisperx transcription or alignment"""
    start: float
    end: float
    text: str

class TranscriptionResult(TypedDict):
    """output of the transcription step from whisperx"""
    segments: List[SegmentDict]

class AlignmentResult(TypedDict):
    """output of the alignment step from whisperx"""
    segments: List[SegmentDict]

class DiarizationSegmentDict(TypedDict, total=False):
    """a single diarization segment"""
    start: float
    end: float
    speaker: str
    label: str

class DiarizationDict(TypedDict): segments: List[DiarizationSegmentDict]

class AlignMetadata(TypedDict):
    """metadata of the alignment model"""
    language: str
    dictionary: Dict[str, int]
    type: str

class WordEntry(TypedDict):
    """word-level entry attached to aligned segments from whisperx"""
    start: float
    end: float
    word: str
    speaker: str | None
