import requests
from requests import Response
from typing import Dict
from transcription import transcribe_with_diarization

# i'm not sure whether this file is needed:
#   unless anything else gets added to it, it should be merged with transcription.py or vice versa
#   or this should be handled in the api 

def download_audio(base_url: str, jobid: str) -> bytes:
    """
    downloads an audio file from the gpu api for the given job id
    constructs a url using base_url and jobid and performs a GET request
    returns the raw response body as bytes
    """
    resp: Response = requests.get(f"{base_url}/queue/{jobid}")  # get request to queue endpoint
    if resp.status_code == 404: raise RuntimeError(f"audio file for job '{jobid}' not found")
    resp.raise_for_status()
    return resp.content

def upload_transcription(base_url: str, jobid: str, text_bytes: bytes) -> None:
    """
    uploads a text transcription to the transcriptions api for the given job id

    sends a multipart/form-data request with the transcription file payload and the job id
    """
    files: Dict[str, tuple[str, bytes, str]] = {"file": ("transcription.txt", text_bytes, "text/plain")} 
    data: Dict[str, str] = {"jobid": jobid}
    resp: Response = requests.post(f"{base_url}/transcriptions", files=files, data=data) # post request to upload transcription
    resp.raise_for_status()

def process_job(base_url: str, jobid: str) -> None:
    """
    processes the transcription pipeline for a single job?

    downloads the audio from the api, runs transcription, and uploads the transcription back to the api
    """
    audio_bytes: bytes = download_audio(base_url=base_url, jobid=jobid) 
    text_bytes: bytes = transcribe_with_diarization(audio_bytes=audio_bytes)
    upload_transcription(base_url=base_url, jobid=jobid, text_bytes=text_bytes)
