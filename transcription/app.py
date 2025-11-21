import os
import asyncio
import subprocess
import requests
from requests import Response
from requests.exceptions import HTTPError
from dotenv import load_dotenv
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Request, WebSocket, WebSocketDisconnect
import jwt
from transcription import generate_diarized_transcript

AUTH_URL = "https://polina-gateway.fly.dev/auth"
AUTH_PUBLIC_KEY = os.environ["AUTH_PUBLIC_KEY"]
FORMAT = "\033[30;43m"
RESET = "\033[0m"

load_dotenv()
app = FastAPI()
queue: list[tuple[str, bytes]] = []
S3_BUCKET: str = "https://s3-aged-water-5651.fly.dev"
currently_processing: bool = False
connections: dict[str, list[WebSocket]] = {}

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

# i say all 
async def broadcast(jobid: str, message: dict):
    """send message to all websocket clients listening for any given jobid"""
    global connections
    # print(f"websocket BROADCAST → {jobid} → {message}") 
    if jobid not in connections: return
    dead = []
    for websocket in connections[jobid]:
        try: await websocket.send_json(message)
        except Exception: dead.append(websocket)
    # cleanup dead sockets
    for websocket in dead: connections[jobid].remove(websocket)

async def _process_queue() -> None:
    """process all jobs that are in queue"""
    global queue
    global currently_processing
    while queue:
        jobid, audio_bytes = queue[0]
        currently_processing = True
        # print(f"{FORMAT}before await broadcast in _process_queue(){RESET}")
        await broadcast(jobid, {"status": "converting"})
        # print(f"{FORMAT}after await broadcast{RESET}")

        try:
            await broadcast(jobid, {"status": "transcribing"})
            transcript_bytes: bytes = await asyncio.to_thread(
                generate_diarized_transcript,
                audio_bytes=audio_bytes,
            )
        except Exception as e:
            # print(f"{FORMAT}IN EXCEPTION{RESET}")
            error_text: str = f"transcription failed for job '{jobid}': {e}"
            # print(f"{FORMAT}{error_text}{RESET}")
            transcript_bytes = error_text.encode("utf-8")
        finally: 
            # print(f"{FORMAT}IN FINALLY{RESET}")
            currently_processing = False
            queue.pop(0)

        
        _post_transcription_to_s3(jobid, transcript_bytes)
        await broadcast(jobid, {"status": "completed"})

def _post_jobid_to_auth(jobid: str, email: str, filename: str) -> None:
    """posts a transcription job id and user email to the auth api"""
    data: dict[str, str] = {"jobid": jobid, "email": email, "filename": filename}
    resp: Response = requests.post(f"{AUTH_URL}/transcriptions/add", json=data)
    try:
        resp.raise_for_status()
    except HTTPError as e: print(f"{FORMAT}mauth error for {email}: {e} {resp.text}{RESET}"); return

def _decode_jwt_email(token: str | None) -> str | None:
    """decodes and returns the email claim from a jwt token"""
    try:
        payload = jwt.decode(token, AUTH_PUBLIC_KEY, algorithms=["RS256"])
    except jwt.PyJWTError:
        return None
    value = payload.get("email")
    if isinstance(value, str):
        return value
    return None

@app.post("/upload")
async def upload(request: Request, file: UploadFile = File(...), jobid: str = Form(...)) -> dict[str, str]:
    """receives an audio blob and a job id, and either forwards the audio to s3 or runs local transcription"""

    global queue
    global currently_processing

    token = request.cookies.get("token")
    jwt_email: str | None = None
    if token: 
        jwt_email = _decode_jwt_email(token)
        # print(f"{FORMAT} {jwt_email} sent a file with token {token}{RESET}")
    
    # print(f"{FORMAT}before awaiting file.read{RESET}")
    audio_bytes: bytes = await file.read()
    # print(f"{FORMAT}received file {file.filename}, before calling _process_queue(){RESET}")
    to_append_to_queue: tuple[str, bytes] = jobid, audio_bytes
    # print(f"{FORMAT}adding {to_append_to_queue} to queue{RESET}")
    queue.append(to_append_to_queue)
    if currently_processing:
        # posts the audio file to s3 bucket's /queue if currently transcribing
        _post_audio_to_s3(jobid, audio_bytes, file.filename)        
        return {"jobid": jobid, "status": "queued"}
    
    if jobid is None: jobid = "you did not provide a jobid"
    try: asyncio.create_task(_process_queue())
    except Exception as e: raise HTTPException(status_code=500, detail=e)
    finally:
        # print(f"{FORMAT}received file '{file.filename}' with jobid '{jobid}', after calling _process_queue(){RESET}")
        if jwt_email: _post_jobid_to_auth(jobid, jwt_email, file.filename)
        return {"jobid": jobid, "status": "completed"}


# TODO: DEPRECATE THIS ENDPOINT IN FAVOR OF WEBSOCKET 
@app.post("/status")
async def get_status(jobid: str) -> dict[str, str]:
    """status endpoint"""
    global queue
    jobids: list[str] = [queued_jobid for queued_jobid, _ in queue]
    if jobid not in jobids: raise HTTPException(status_code=404, detail="job not found")

    if jobids[0] == jobid: return {"jobid": jobid, "status": "transcribing"}
    return {"jobid": jobid, "status": "queued"}


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
        # print(f"{FORMAT} WEBSOCKET INIT {init}{RESET}")
        jobid = init.get("jobid")
        
        if not jobid: await websocket.close(code=4000); return

        await websocket.send_json({"status": "connected"})
        # print(f"{FORMAT} currently_processing {currently_processing}")
        # if queue: print(f"queue exists")
        # print(f"\n jobid {jobid} \n {RESET}")
        if currently_processing and queue and queue[0][0] == jobid: await websocket.send_json({"status": "processing"})
        elif any(queued_jobid == jobid for queued_jobid, _ in queue): await websocket.send_json({"status": "queued"})
        else: await websocket.send_json({"status": "not found"})

        if jobid not in connections: connections[jobid] = []
        connections[jobid].append(websocket)
        # print(connections)

        while True: await websocket.receive_text()  # not used
    except WebSocketDisconnect:
        # cleanup
        for _, socket_list in connections.items():
            if websocket in socket_list: socket_list.remove(websocket)
        return