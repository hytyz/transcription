import requests
from requests import Response
from typing import Dict
from transcription import generate_diarized_transcript, get_current_state

# i'm not sure whether this file is needed:
#   unless anything else gets added to it, it should be merged with transcription.py or vice versa
#   or this should be handled in the api 
#   either way it was probably helpful to try to figure out how this is going to work

def download_audio(base_url: str, jobid: str) -> bytes:
    """
    downloads an audio file from the gpu api for the given job id
    constructs a url using base_url and jobid and performs a get request
    returns the raw response body as bytes
    """
    resp: Response = requests.get(f"{base_url}/queue/{jobid}")  # get request to queue endpoint
    if resp.status_code == 404: raise RuntimeError(f"audio file for job '{jobid}' not found")
    resp.raise_for_status()
    return resp.content

def upload_transcription(base_url: str, jobid: str, text_bytes: bytes) -> None:
    """
    uploads a text transcription to the transcriptions api for the given job id

    sends a multipart/form-data post request with the transcription file payload and the job id
    """
    files: Dict[str, tuple[str, bytes, str]] = {"file": ("transcription.txt", text_bytes, "text/plain")} 
    data: Dict[str, str] = {"jobid": jobid}
    resp: Response = requests.post(f"{base_url}/transcriptions", files=files, data=data) # post request to upload transcription
    resp.raise_for_status()

def process_job(base_url: str, jobid: str) -> None:
    """
    run the full transcription pipeline for a single job?

    downloads the audio from the api, 
    runs the transcription and diarization pipeline,
    reports state changes to the status endpoint,
    uploads the final transcription back to the api
    """
    audio_bytes: bytes = download_audio(base_url=base_url, jobid=jobid)
    def _report_state(state: str) -> None: 
        try: upload_status(base_url=base_url, jobid=jobid, state=state) 
        except Exception: pass

    text_bytes: bytes = generate_diarized_transcript(audio_bytes=audio_bytes, on_state_change=_report_state)
    upload_transcription(base_url=base_url, jobid=jobid, text_bytes=text_bytes)

def upload_status(base_url: str, jobid: str, state: str) -> None:
    """
    uploads the current pipeline state to the endpoint
    sends a post request to /status containing the job id and the current state label
    """
    data: Dict[str, str] = {"jobid": jobid, "state": state}
    resp: Response = requests.post(f"{base_url}/status", json=data)
    resp.raise_for_status()

def get_transcription_state() -> str:
    """
    returns the current transcription pipeline state from the transcription module
    """
    return get_current_state()
