import requests; from requests import Response
from transcription import generate_diarized_transcript
from dotenv import load_dotenv; from fastapi import FastAPI
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Request, WebSocket, WebSocketDisconnect
from requests.exceptions import HTTPError
import asyncio; import os; import jwt; import re; import json; import logging
from asyncio import AbstractEventLoop
from typing import Final
from datetime import datetime

class JSONFormatter(logging.Formatter):
    def format(self, record):
        log_obj = {
            "timestamp": datetime.now().isoformat(),
            "level": record.levelname.lower(),
            "service": "transcription",
            "message": record.getMessage(),
        }
        if hasattr(record, 'extra_data'): log_obj.update(record.extra_data)
        return json.dumps(log_obj)

logger = logging.getLogger("transcription")
logger.setLevel(logging.DEBUG if os.environ.get("LOG_LEVEL") == "debug" else logging.INFO)
handler = logging.StreamHandler()
handler.setFormatter(JSONFormatter())
logger.handlers = [handler]

def log_with_extra(level, message, **kwargs):
    """log with extra metadata"""
    record = logging.LogRecord(
        name="transcription", level=level, pathname="", lineno=0,
        msg=message, args=(), exc_info=None
    )
    record.extra_data = kwargs
    logger.handle(record)

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

log_with_extra(logging.INFO, "transcription service initialized", auth_url=AUTH_URL, s3_bucket=S3_BUCKET)

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
    log_with_extra(logging.DEBUG, "posting audio to s3", jobid=jobid, filename=safe_filename, size=len(audio_bytes))
    resp: Response = requests.post(f"{S3_BUCKET}/queue", files=files, data=data)
    resp.raise_for_status()
    log_with_extra(logging.INFO, "audio posted to s3", jobid=jobid, status=resp.status_code)

def _post_transcription_to_s3(jobid: str, transcript_bytes: bytes) -> None:
    """posts a transcription blob and its job id to the s3 /transcriptions endpoint"""

    files: dict[str, tuple[str, bytes, str]] = {
        "file": ("transcription.txt", transcript_bytes, "text/plain")
    }
    data: dict[str, str] = {"jobid": jobid}
    log_with_extra(logging.DEBUG, "posting transcription to s3", jobid=jobid, size=len(transcript_bytes))
    resp: Response = requests.post(f"{S3_BUCKET}/transcriptions", files=files, data=data)
    resp.raise_for_status()
    log_with_extra(logging.INFO, "transcription posted to s3", jobid=jobid, status=resp.status_code)

async def broadcast(jobid: str, message: dict):
    """send message to all websocket clients listening for any given jobid"""
    global connections
    if jobid not in connections: return
    dead = []
    log_with_extra(logging.DEBUG, "broadcasting to websockets", jobid=jobid, message=message, client_count=len(connections[jobid]))
    for websocket in connections[jobid]:
        try: await websocket.send_json(message)
        except Exception as e:
            log_with_extra(logging.WARN, "websocket send failed", jobid=jobid, error=str(e))
            dead.append(websocket)
    for websocket in dead: connections[jobid].remove(websocket)

async def _process_queue() -> None:
    """process all jobs that are in queue"""
    global queue
    global currently_processing
    while queue:
        jobid, audio_bytes = queue[0]
        currently_processing = True
        loop: AbstractEventLoop = asyncio.get_running_loop()
        log_with_extra(logging.INFO, "processing job", jobid=jobid, queue_size=len(queue), audio_size=len(audio_bytes))

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
            log_with_extra(logging.INFO, "job completed", jobid=jobid, transcript_size=len(transcript_bytes))

        except Exception as e:
            error_text: str = f"transcription failed for job '{jobid}': {e}"
            log_with_extra(logging.ERROR, "job failed", jobid=jobid, error=str(e))
            await broadcast(jobid, {"status": "error", "error": error_text})
            _post_transcription_to_s3(jobid, error_text.encode("utf-8"))
        finally: 
            currently_processing = False
            queue.pop(0)
            if jobid in connections:
                del connections[jobid]
            log_with_extra(logging.DEBUG, "job removed from queue", jobid=jobid, remaining=len(queue))


def _post_jobid_to_auth(jobid: str, email: str, filename: str) -> None:
    """posts a transcription job id and user email to the auth api"""
    data: dict[str, str] = {"jobid": jobid, "email": email, "filename": filename}
    headers: dict[str, str] = {"X-API-Key": INTERNAL_TOKEN}
    log_with_extra(logging.DEBUG, "posting jobid to auth", jobid=jobid, email=email)
    resp: Response = requests.post(f"{AUTH_URL}/transcriptions/add", json=data, headers=headers)
    try:
        resp.raise_for_status()
        log_with_extra(logging.INFO, "jobid registered with auth", jobid=jobid, email=email)
    except HTTPError as e:
        log_with_extra(logging.ERROR, "auth error", jobid=jobid, email=email, error=str(e), response=resp.text)
        return

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
    log_with_extra(logging.INFO, "upload received", jobid=jobid, filename=file.filename, size=len(audio_bytes), email=jwt_email, queue_size=len(queue))
    
    to_append_to_queue: tuple[str, bytes] = jobid, audio_bytes
    queue.append(to_append_to_queue)
    if currently_processing:
        # posts the audio file to s3 bucket's /queue if currently transcribing
        log_with_extra(logging.INFO, "job queued (processing in progress)", jobid=jobid)
        _post_audio_to_s3(jobid, audio_bytes, file.filename)        
        return {"jobid": jobid, "status": "queued"}
    
    if jobid is None: jobid = "you did not provide a jobid"
    try:
        log_with_extra(logging.INFO, "starting job processing", jobid=jobid)
        asyncio.create_task(_process_queue())
    except Exception as e:
        log_with_extra(logging.ERROR, "failed to create processing task", jobid=jobid, error=str(e))
        raise HTTPException(status_code=500, detail=str(e))
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
    client_ip = websocket.client.host if websocket.client else "unknown"
    log_with_extra(logging.DEBUG, "websocket connection accepted", client_ip=client_ip)
    try:
        # first message from client MUST be: {"jobid": "..."}
        init = await websocket.receive_json()
        jobid = init.get("jobid")
        
        if not jobid:
            log_with_extra(logging.WARN, "websocket closed: no jobid provided", client_ip=client_ip)
            await websocket.close(code=4000)
            return

        log_with_extra(logging.INFO, "websocket subscribed to job", jobid=jobid, client_ip=client_ip)
        await websocket.send_json({"status": "connected"})

        if any(queued_jobid == jobid for queued_jobid, _ in queue): await websocket.send_json({"status": "queued"})
        elif not (currently_processing and queue and queue[0][0] == jobid): await websocket.send_json({"status": "not found"})

        if jobid not in connections: connections[jobid] = []
        connections[jobid].append(websocket)

        while True: await websocket.receive_text()  # not used
    except WebSocketDisconnect:
        log_with_extra(logging.DEBUG, "websocket disconnected", client_ip=client_ip)
        # cleanup websocket from connections and remove empty jobid keys
        empty_keys = []
        for jobid_key, socket_list in connections.items():
            if websocket in socket_list: socket_list.remove(websocket)
            if not socket_list: empty_keys.append(jobid_key)
        for key in empty_keys:
            del connections[key]
        return