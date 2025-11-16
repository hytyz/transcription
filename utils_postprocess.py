from math import isfinite, ceil
from pandas import DataFrame
from re import compile, Pattern
from utils_types import TranscriptionError, SegmentDict, AlignmentResult, SpeakerSegment, WordEntry

_TIME_GRID_CELL: float = 2.0 # duration in seconds of each time grid cell for indexing diarization turns
leading_punctuation_regex: Pattern[str] = compile(r"^[\.\,\!\?\;\:\%\)\]\}]")

def merge_text(previous_text: str, next_text: str) -> str:
    """merges two strings, inserting spaces only when appropriate"""
    previous_text = (previous_text or "").rstrip()
    next_text = (next_text or "").lstrip()
    if not previous_text: return next_text  # the merged result is just the new text
    if not next_text: return previous_text  # nothing to append
    last_char: str = previous_text[-1]
    if last_char in "-([{\"'": return previous_text + next_text
    if leading_punctuation_regex.match(next_text): return previous_text + next_text 
    return previous_text + " " + next_text

def fill_missing_word_speakers(alignment_result: AlignmentResult, diarization_result: DataFrame) -> None:
    """
    fills missing word "speaker" fields in alignment_result using diarization turns

    normalises diarization into SpeakerSegment turns, uses the time grid index to pick labels for each word interval, 
    and falls back to the previous word label in the same segment when needed.
    mutates alignment_result and doesn't return anything
    """
    segments: list[SegmentDict] = alignment_result.get("segments") or []
    if not isinstance(segments, list): raise TranscriptionError("alignment_result must contain a segments list")
    # converts diarization_result into a list of SpeakerSegment
    turns: list[SpeakerSegment] = _normalise_diarisation_turns(diarization_result)

    # dictionary that maps cell indices to lists of SpeakerSegment, 
    # used to find candidate speaker segments for each word
    turn_index: dict[int, list[SpeakerSegment]] = _build_turn_index(turns)

    for segment in segments:
        raw_words = segment.get("words") or []
        if not isinstance(raw_words, list): continue
        words: list[WordEntry] = raw_words
        previous_label: str | None = None # last known label inside this segment; used as a fallback

        for word in words:
            start_value: float = word.get("start")
            end_value: float = word.get("end")
            if not isinstance(start_value, (int, float)) or not isinstance(end_value, (int, float)): continue
            # already labelled by assign_word_speakers; remember and move on
            if "speaker" in word and word["speaker"]: previous_label = str(word["speaker"]); continue
            # primary source for backfilling -- label derived from overlapping diarization turns
            label: str | None = _pick_speaker_for_interval(float(start_value), float(end_value), turn_index)
            if label is None and previous_label is not None: label = previous_label
            if label is None: continue
            word["speaker"] = label
            previous_label = label

def format_timestamp(total_seconds: float) -> str:
    hours: int = int(total_seconds // 3600)
    minutes: int = int((total_seconds % 3600) // 60)
    seconds: int = int(total_seconds % 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"

def _normalise_diarisation_turns(diarization_result: DataFrame) -> list[SpeakerSegment]:
    """
    normalises diarization rows into cleaned SpeakerSegment turns

    drops rows with invalid times, sets negative times to 0.0, enforces positive duration,
    and returns segments sorted by (start, end).
    """
    segments: list[SpeakerSegment] = []
    if not isinstance(diarization_result, DataFrame): raise TranscriptionError("diarization_result must be a pandas DataFrame")

    for _, row in diarization_result.iterrows():
        start_value = row.get("start")
        end_value = row.get("end")
        if start_value is None or end_value is None: continue
        if not isinstance(start_value, (int, float)) or not isinstance(end_value, (int, float)): continue
        
        start_seconds: float = float(start_value)
        end_seconds: float = float(end_value)
        if not (isfinite(start_seconds) and isfinite(end_seconds)): continue
        if start_seconds < 0.0: start_seconds = 0.0
        if end_seconds < 0.0: end_seconds = 0.0
        if end_seconds <= start_seconds: continue
        
        label = row.get("speaker") or row.get("label") or "UNKNOWN"
        label_value: str = str(label)

        segments.append(SpeakerSegment(start=start_seconds, end=end_seconds, label=label_value))

    segments.sort(key=lambda segment: (segment.start, segment.end))
    return segments

def _build_turn_index(turns: list[SpeakerSegment]) -> dict[int, list[SpeakerSegment]]:
    """
    builds an index of speaker turns keyed by time cells

    each SpeakerSegment is assigned to every cell that overlaps its [start, end) interval
    """
    # keys are time cell indices; values are lists of SpeakerSegment instances that overlap that cell index
    turn_index: dict[int, list[SpeakerSegment]] = {} 
    for turn in turns:
        start_cell_index: int = int(turn.start // _TIME_GRID_CELL) # which cell contains the start time of the current turn
        end_cell_index: int = int(ceil(turn.end / _TIME_GRID_CELL)) # the cell index after the last cell the segment overlaps
        for cell_index in range(start_cell_index, end_cell_index):
            # each cell_index value in this range, register the current turn under that cell
            cell_turns: list[SpeakerSegment] | None = turn_index.get(cell_index)
            if cell_turns is None: turn_index[cell_index] = [turn]
            else: cell_turns.append(turn)
    return turn_index

def _pick_speaker_for_interval(interval_start: float, interval_end: float, turn_index: dict[int, list[SpeakerSegment]]) -> str | None:
    """
    picks a speaker label for [interval_start, interval_end) from diarization turns using a time grid index

    computes overlap only against turns that fall into the cells that overlap the interval
    returns the label of the turn with the largest overlap, or None if no turns overlap
    """
    if interval_end <= interval_start: return None

    epsilon: float = 1e-9
    start_cell_index: int = int(interval_start // _TIME_GRID_CELL) # cell index that contains the interval start time
    end_cell_index: int = int((interval_end - epsilon) // _TIME_GRID_CELL) + 1 # cell index one past the last cell that the query interval should cover

    best_label: str | None = None
    best_overlap: float = 0.0

    # a turn can be stored in multiple cells, this is to track which turns have already been processed for this query
    visited_turn_ids: set[int] = set() 

    for cell_index in range(start_cell_index, end_cell_index):
        cell_turns: list[SpeakerSegment] | None = turn_index.get(cell_index)
        if not cell_turns: continue

        for turn in cell_turns:
            turn_id: int = id(turn) # to detect duplicates
            if turn_id in visited_turn_ids: continue
            visited_turn_ids.add(turn_id)

            overlap_start: float = max(interval_start, turn.start) # start of overlap between query interval and diarization segment
            overlap_end: float = min(interval_end, turn.end) # end of overlap
            if overlap_end <= overlap_start: continue

            overlap_duration: float = overlap_end - overlap_start
            # if current overlap is > best_overlap, updates best_overlap to current overlap, same with label
            if overlap_duration > best_overlap: best_overlap = overlap_duration; best_label = turn.label
    return best_label
