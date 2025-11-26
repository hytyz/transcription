import requests; from requests import Response
from transcription import generate_diarized_transcript
from dotenv import load_dotenv; from fastapi import FastAPI
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Request, WebSocket, WebSocketDisconnect
from requests.exceptions import HTTPError
import asyncio; import os; import jwt; import re
from asyncio import AbstractEventLoop
from typing import Final

AUTH_URL: Final[str]  = "https://polina-gateway.fly.dev/auth"
AUTH_PUBLIC_KEY: Final[str] = os.environ["AUTH_PUBLIC_KEY"]
INTERNAL_TOKEN: Final[str] = os.environ.get("INTERNAL_TOKEN", "")
S3_BUCKET: Final[str] = "https://s3-aged-water-5651.fly.dev"
FORMAT: Final[str] = "\033[30;43m"
RESET: Final[str] = "\033[0m"

load_dotenv()
app = FastAPI()
queue: list[tuple[str, bytes]] = []
currently_processing: bool = False
connections: dict[str, list[WebSocket]] = {}

def _sanitise_filename(filename: str | None) -> str:
    """sanitises a filename to remove path traversal and special characters"""
    if not filename:
        return "audio"
    sanitised = re.sub(r'[\.]{2,}', '', filename)  # remove ..
    sanitised = re.sub(r'[/\\\0]', '', sanitised)  # remove slashes and null bytes
    sanitised = re.sub(r'[^a-zA-Z0-9._-]', '_', sanitised)  # replace special chars
    return sanitised[:255] if sanitised else "audio"

def _post_audio_to_s3(jobid: str, audio_bytes: bytes, filename: str | None) -> None:
    """posts an audio blob and its job id to the s3 /queue endpoint"""
    safe_filename = _sanitise_filename(filename)
    files: dict[str, tuple[str, bytes, str]] = {
        "file": (safe_filename, audio_bytes, "application/octet-stream")
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

async def broadcast(jobid: str, message: dict):
    """send message to all websocket clients listening for any given jobid"""
    global connections
    if jobid not in connections: return
    dead = []
    for websocket in connections[jobid]:
        try: await websocket.send_json(message)
        except Exception: dead.append(websocket)
    for websocket in dead: connections[jobid].remove(websocket)

async def _process_queue() -> None:
    """process all jobs that are in queue"""
    global queue
    global currently_processing
    while queue:
        jobid, audio_bytes = queue[0]
        currently_processing = True
        loop: AbstractEventLoop = asyncio.get_running_loop()

        def _threadsafe_status(status: str) -> None:
            asyncio.run_coroutine_threadsafe(broadcast(jobid, {"status": status}), loop)
        try:
            transcript_bytes: bytes = await asyncio.to_thread(
                generate_diarized_transcript,
                audio_bytes=audio_bytes,
                on_status=_threadsafe_status,
            )
            _post_transcription_to_s3(jobid, transcript_bytes)
            await broadcast(jobid, {"status": "completed"})

        except Exception as e:
            error_text: str = f"transcription failed for job '{jobid}': {e}"
            await broadcast(jobid, {"status": "error", "error": error_text})
            _post_transcription_to_s3(jobid, error_text.encode("utf-8"))
        finally: 
            currently_processing = False
            queue.pop(0)
            if jobid in connections:
                del connections[jobid]


def _post_jobid_to_auth(jobid: str, email: str, filename: str) -> None:
    """posts a transcription job id and user email to the auth api"""
    data: dict[str, str] = {"jobid": jobid, "email": email, "filename": filename}
    headers: dict[str, str] = {"X-API-Key": INTERNAL_TOKEN}
    resp: Response = requests.post(f"{AUTH_URL}/transcriptions/add", json=data, headers=headers)
    try:
        resp.raise_for_status()
    except HTTPError as e: print(f"{FORMAT}mauth error for {email}: {e} {resp.text}{RESET}"); return

def _decode_jwt_email(token: str | None) -> str | None:
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
    
    to_append_to_queue: tuple[str, bytes] = jobid, audio_bytes
    queue.append(to_append_to_queue)
    if currently_processing:
        # posts the audio file to s3 bucket's /queue if currently transcribing
        _post_audio_to_s3(jobid, audio_bytes, file.filename)        
        return {"jobid": jobid, "status": "queued"}
    
    if jobid is None: jobid = "you did not provide a jobid"
    try: asyncio.create_task(_process_queue())
    except Exception as e: raise HTTPException(status_code=500, detail=str(e))
    finally:
        if jwt_email: _post_jobid_to_auth(jobid, jwt_email, file.filename)
        return {"jobid": jobid, "status": "accepted"}

@app.websocket("/ws/status")
async def websocket_status(websocket: WebSocket):
    """websocket endpoint for real-time transcription status updates"""
    global connections
    global queue
    global currently_processing
    await websocket.accept()
    try:
        # first message from client MUST be: {"jobid": "..."}
        init = await websocket.receive_json()
        jobid = init.get("jobid")
        
        if not jobid: await websocket.close(code=4000); return

        await websocket.send_json({"status": "connected"})

        if any(queued_jobid == jobid for queued_jobid, _ in queue): await websocket.send_json({"status": "queued"})
        elif not (currently_processing and queue and queue[0][0] == jobid): await websocket.send_json({"status": "not found"})

        if jobid not in connections: connections[jobid] = []
        connections[jobid].append(websocket)

        while True: await websocket.receive_text()  # not used
    except WebSocketDisconnect:
        # cleanup websocket from connections and remove empty jobid keys
        empty_keys = []
        for jobid_key, socket_list in connections.items():
            if websocket in socket_list: socket_list.remove(websocket)
            if not socket_list: empty_keys.append(jobid_key)
        for key in empty_keys:
            del connections[key]
        return