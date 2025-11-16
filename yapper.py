import requests
from requests import Response
from transcription import generate_diarized_transcript, get_current_state

# i'm very sure this file is not needed at all
# this should be handled in the api
# but it was kinda fun to try to figure out how this could interact with the api so whatever. blueprint i suppose

def download_audio(base_url: str, jobid: str) -> bytes:
    """downloads raw audio bytes for a job id from api"""
    resp: Response = requests.get(f"{base_url}/queue/{jobid}")  # get request to queue endpoint
    if resp.status_code == 404: raise RuntimeError(f"audio file for job '{jobid}' not found")
    resp.raise_for_status()
    return resp.content

def upload_transcription(base_url: str, jobid: str, text_bytes: bytes) -> None:
    """uploads a text transcription for a job id to api"""
    files: dict[str, tuple[str, bytes, str]] = {"file": ("transcription.txt", text_bytes, "text/plain")} 
    data: dict[str, str] = {"jobid": jobid}
    resp: Response = requests.post(f"{base_url}/transcriptions", files=files, data=data) # post request to upload transcription
    resp.raise_for_status()

def process_job(base_url: str, jobid: str) -> None:
    """runs the full transcription pipeline for a single job?"""
    audio_bytes: bytes = download_audio(base_url=base_url, jobid=jobid)
    def _report_state(state: str) -> None: 
        try: upload_status(base_url=base_url, jobid=jobid, state=state) 
        except Exception: pass

    text_bytes: bytes = generate_diarized_transcript(audio_bytes=audio_bytes, on_state_change=_report_state)
    upload_transcription(base_url=base_url, jobid=jobid, text_bytes=text_bytes)

def upload_status(base_url: str, jobid: str, state: str) -> None:
    """posts the current pipeline state for a job id to /status"""
    data: dict[str, str] = {"jobid": jobid, "state": state}
    resp: Response = requests.post(f"{base_url}/status", json=data)
    resp.raise_for_status()

def get_transcription_state() -> str: return get_current_state()
