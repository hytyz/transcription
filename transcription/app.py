import requests; from requests import Response
from transcription import generate_diarized_transcript
from dotenv import load_dotenv; from fastapi import FastAPI
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Request
from requests.exceptions import HTTPError
import asyncio
import os
from typing import Optional
import jwt

AUTH_URL = "https://polina-gateway.fly.dev/auth"
AUTH_PUBLIC_KEY = os.environ["AUTH_PUBLIC_KEY"]
FORMAT = "\033[30;43m"
RESET = "\033[0m"

load_dotenv()
app = FastAPI()
queue: list[tuple[str, bytes]] = []
S3_BUCKET: str = "https://s3-aged-water-5651.fly.dev"
currently_processing: bool = False

def _post_audio_to_s3(jobid: str, audio_bytes: bytes, filename: str | None) -> None:
    """posts an audio blob and its job id to the s3 /queue endpoint"""
    files: dict[str, tuple[str, bytes, str]] = {
        "file": (filename or "audio", audio_bytes, "application/octet-stream")
    }
    data: dict[str, str] = {"jobid": jobid}
    resp: Response = requests.post(f"{S3_BUCKET}/queue", files=files, data=data)
    resp.raise_for_status()

def _post_transcription_to_s3(jobid: str, transcript_bytes: bytes) -> None:
    """posts a transcription blob and its job id to the s3 /transcriptions endpoint"""
        
    files: dict[str, tuple[str, bytes, str]] = {
        "file": ("transcription.txt", transcript_bytes, "text/plain")
    }
    data: dict[str, str] = {"jobid": jobid}
    resp: Response = requests.post(f"{S3_BUCKET}/transcriptions", files=files, data=data)
    resp.raise_for_status()

async def _process_queue() -> None:
    """process all jobs that are in queue"""
    global queue
    global currently_processing
    while queue:
        jobid, audio_bytes = queue[0]
        currently_processing = True
        try: 
            transcript_bytes: bytes = await asyncio.to_thread(
                generate_diarized_transcript,
                audio_bytes=audio_bytes,
            )
        except Exception as e:
            error_text: str = f"transcription failed for job '{jobid}': {e}"
            transcript_bytes = error_text.encode("utf-8")
        finally: 
            currently_processing = False
            queue.pop(0)

        _post_transcription_to_s3(jobid, transcript_bytes)

def _post_jobid_to_auth(jobid: str, email: str, filename: str) -> None:
    """posts a transcription job id and user email to the auth api"""
    data: dict[str, str] = {"jobid": jobid, "email": email, "filename": filename}
    resp: Response = requests.post(f"{AUTH_URL}/transcriptions/add", json=data)
    try:
        resp.raise_for_status()
    except HTTPError as e: print(f"\033[30;43mauth error for {email}: {e} {resp.text}\033[0m"); return

def _decode_jwt_email(token: Optional[str]) -> Optional[str]:
    """decodes and returns the email claim from a jwt token"""
    try: payload = jwt.decode(token, AUTH_PUBLIC_KEY, algorithms=["RS256"])
    except jwt.PyJWTError: return None
    value = payload.get("email")
    if isinstance(value, str): return value
    return None

@app.post("/upload")
async def upload(request: Request, file: UploadFile = File(...), jobid: str = Form(...)) -> dict[str, str]:
    """receives an audio blob and a job id, and either forwards the audio to s3 or runs local transcription"""

    global queue
    global currently_processing

    token = request.cookies.get("token")
    jwt_email: str | None = None
    if token: jwt_email = _decode_jwt_email(token)

    
    audio_bytes: bytes = await file.read()

    queue.append((jobid, audio_bytes))
    if currently_processing:
        # posts the audio file to s3 bucket's /queue if currently transcribing
        _post_audio_to_s3(jobid, audio_bytes, file.filename)        
        return {"jobid": jobid, "status": "queued"}
    
    if jobid is None: jobid = "you did not provide a jobid"

    asyncio.create_task(_process_queue())
    # print filename
    # print(f"{FORMAT}received file '{file.filename}' with jobid '{jobid}'{RESET}")
    if jwt_email: _post_jobid_to_auth(jobid, jwt_email, file.filename)
    return {"jobid": jobid, "status": "completed"}

@app.post("/status")
async def get_status(jobid: str) -> dict[str, str]:
    """status endpoint"""
    global queue
    jobids: list[str] = [queued_jobid for queued_jobid, _ in queue]
    if jobid not in jobids: raise HTTPException(status_code=404, detail="job not found")

    if jobids[0] == jobid: return {"jobid": jobid, "status": "transcribing"}
    return {"jobid": jobid, "status": "queued"}
