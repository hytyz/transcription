import os

asr_options = {
    "beam_size": 7,
    "patience": 1.2,
    "hotwords": os.environ.get("HOTWORDS", "").strip() or None,
    "suppress_numerals": True,
}
