from dataclasses import dataclass, field

#internal data structures

class TranscriptionError(Exception): pass

@dataclass(frozen=True)
class Duration:
    """time bounds in seconds [x,y)"""
    start: float
    end: float

@dataclass
class Segment:
    """text segment with timing"""
    duration: Duration
    text: str

@dataclass
class WordEntry:
    """word-level entry attached to aligned segments from whisperx"""
    duration: Duration
    word: str
    speaker: str | None

@dataclass
class WordAlignedSegment(Segment):
    """segment with text decomposed into word aligned entries"""
    words: list[WordEntry] = field(default_factory=list)

# external api views

@dataclass
class AlignmentResult:
    """segments produced by the alignment stage"""
    segments: list[WordAlignedSegment]

@dataclass
class TranscriptionResult:
    """output of the transcription step from whisperx"""
    segments: list[Segment]

@dataclass
class SpeakerSegment:
    """diarization-only turn, no text"""
    duration: Duration
    label:str

@dataclass
class Utterance:
    """final merged utterance"""
    duration: Duration
    speaker: str
    text:str

@dataclass
class DiarizationSegment:
    """a single diarization segment"""
    duration: Duration
    speaker: str | None
    label: str | None

@dataclass
class Diarization:
    """container for diarization segments"""
    segments: list[DiarizationSegment]

@dataclass
class AlignMetadata:
    """metadata of the alignment model"""
    language: str
    dictionary: dict[str, int]
    type: str

# helpers 
def _duration_from(d: dict) -> Duration:
    return Duration(start=float(d.get("start", 0.0)), end=float(d.get("end", 0.0)))

def _duration_to(d: Duration) -> dict:
    return {"start": d.start, "end": d.end}

def segment_from_whisper(d: dict) -> Segment:
    return Segment(duration=_duration_from(d), text=str(d.get("text", "")))

def segment_to_whisper(s: Segment) -> dict:
    out = _duration_to(s.duration)
    out["text"] = s.text
    return out

def transcription_result_from_whisper(d: dict) -> TranscriptionResult:
    return TranscriptionResult(segments=[segment_from_whisper(sd) for sd in d.get("segments", [])])

def transcription_result_to_whisper(r: TranscriptionResult) -> dict:
    return {"segments": [segment_to_whisper(s) for s in r.segments]}

def word_from_whisper(d: dict) -> WordEntry:
    return WordEntry(duration=_duration_from(d), word=str(d.get("word", "")), speaker=d.get("speaker"))

def word_to_whisper(w: WordEntry) -> dict:
    out = _duration_to(w.duration)
    out["word"] = w.word
    if w.speaker is not None: out["speaker"] = w.speaker
    return out

def word_aligned_segment_from_whisper(d: dict) -> WordAlignedSegment:
    base = segment_from_whisper(d)
    return WordAlignedSegment(duration=base.duration, 
                              text=base.text, 
                              words=[word_from_whisper(w) for w in d.get("words", [])])

def word_aligned_segment_to_whisper(s: WordAlignedSegment) -> dict:
    out = segment_to_whisper(s)
    out["words"] = [word_to_whisper(w) for w in s.words]
    return out

def alignment_result_from_whisper(d: dict) -> AlignmentResult:
    return AlignmentResult(segments=[word_aligned_segment_from_whisper(sd) for sd in d.get("segments", [])])

def alignment_result_to_whisper(r: AlignmentResult) -> dict:
    return {"segments": [word_aligned_segment_to_whisper(s) for s in r.segments]}

def align_metadata_from_whisper(d: dict) -> AlignMetadata:
    return AlignMetadata(language=str(d.get("language", "")), 
                         dictionary=dict(d.get("dictionary", {})), 
                         type=str(d.get("type", "")))

def align_metadata_to_whisper(m: AlignMetadata) -> dict:
    return {"language": m.language, "dictionary": m.dictionary, "type": m.type}
