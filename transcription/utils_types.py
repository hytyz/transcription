from dataclasses import dataclass
from typing import TypedDict # TODO refactor into dataclass

#internal data structures

# TODO refactor all the start and end into duration dataclass

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
@dataclass 
class SegmentDict:
    """raw segment from whisperx transcription or alignment"""
    start: float
    end: float
    text: str

class TranscriptionResult(TypedDict):
    """output of the transcription step from whisperx"""
    segments: list[SegmentDict]

class WordEntry(TypedDict):
    """word-level entry attached to aligned segments from whisperx"""
    start: float
    end: float
    word: str
    speaker: str | None

class WordAlignedSegmentDict(SegmentDict):
    """segment with start, end, text, and its list of aligned word entries"""
    words: list[WordEntry]

class AlignmentResult(TypedDict):
    """container for the alignment step output holding a list of word-aligned segments"""
    segments: list[WordAlignedSegmentDict]

class DiarizationSegmentDict(TypedDict, total=False):
    """a single diarization segment"""
    start: float
    end: float
    speaker: str
    label: str

class DiarizationDict(TypedDict): 
    segments: list[DiarizationSegmentDict]

class AlignMetadata(TypedDict):
    """metadata of the alignment model"""
    language: str
    dictionary: dict[str, int]
    type: str

