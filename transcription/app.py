import requests
from requests import Response
from transcription import generate_diarized_transcript, get_current_state
from dotenv import load_dotenv
from fastapi import FastAPI
from typing import Dict

from dotenv import load_dotenv
from fastapi import FastAPI, UploadFile, HTTPException

from transcription import generate_diarized_transcript, get_current_state


load_dotenv()

queue: list = []
current_file: bytes
transcript_bytes: bytes
S3_BUCKET: str = "https://s3-aged-water-5651.fly.dev/"

# + receives audio files from gateway (from a client POST) and from s3 bucket's /transcriptions
# + POSTs the audio file to s3 bucket's /queue if currently transcribing (get_status from transcription.py) or received return from transcription_py 
# + POSTs the text file (return from transcription.py) to s3 bucket's /transcriptions endpoint for audio files /queue that exists on s3
# + POSTs the return from transcription.py to /transcriptions
# + has an endpoint for status /status (looks at the queue and if first in queue => get_status from transcription.py elif not in queue => return 404) 
# + if transcription.py throws an exception POSTs the error message to /transcription

# has a queue of job ids (pops the file after transcription.py returns)

app = FastAPI()

def _process_queue() -> None:
    global current_file
    while queue:
        jobid: str = queue[0]
        try: transcript_bytes: bytes = generate_diarized_transcript(audio_bytes=current_file)
        except Exception as e: transcript_bytes.write_bytes(str(e))

        if queue and queue[0] == jobid: queue.pop(0)


@app.post("/queue")
async def enqueue_job(file: UploadFile, jobid: str) -> Dict[str, str]:
    """
    endpoint for other services to POST audio files
    """
    global current_file
    data: bytes = await file.read()
    current_state: str = get_current_state()
    if current_state is not "idle" and jobid not in queue:
        queue.append(jobid)
        current_file = data
        _process_queue(jobid)
        return {"jobid": jobid, "status": "received"}
    if jobid not in queue: queue.append(jobid)

    data: Dict[str, str] = {"jobid": jobid}

    resp: Response = requests.post(f"{S3_BUCKET}/queue", data=data)
    resp.raise_for_status()

    return {"jobid": jobid, "status": "queued"}


@app.post("/status")
async def get_status(jobid: str) -> Dict[str, str]:
    """
    status endpoint

    if job is first in queue, returns the current pipeline state from transcription.py
    if job is later in the queue, reports queued
    """
    if jobid in queue:
        if queue[0] == jobid: return {"jobid": jobid, "status": "processing", "pipeline_state": get_current_state()}
        return {"jobid": jobid, "status": "queued"}

    raise HTTPException(status_code=404, detail="job not found")


@app.post("/transcriptions")
async def get_transcription(jobid: str) -> str:
    """
    returns the transcription text for a completed job
    """
    global transcript_bytes
    transcript_bytes = transcript_bytes.get(jobid)
    if transcript_bytes is None: raise HTTPException(status_code=404, detail="transcription not found")
    return transcript_bytes.decode("utf-8", errors="replace")

def get_transcription_state() -> str: return get_current_state()


# OLD STUFF FROM YAPPER

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
