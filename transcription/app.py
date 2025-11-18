import requests; from requests import Response
from transcription import generate_diarized_transcript, get_current_state
from dotenv import load_dotenv; from fastapi import FastAPI
from fastapi import FastAPI, UploadFile, File, Form, HTTPException

# + receives audio files from gateway (from a client POST) and from s3 bucket's /transcriptions
# + POSTs the audio file to s3 bucket's /queue if currently transcribing (get_status from transcription.py) or received return from transcription_py 
# + POSTs the text file (return from transcription.py) to s3 bucket's /transcriptions endpoint for audio files /queue that exists on s3
# + POSTs the return from transcription.py to /transcriptions
# + has an endpoint for status /status (looks at the queue and if first in queue => get_status from transcription.py elif not in queue => return 404) 
# + if transcription.py throws an exception POSTs the error message to /transcription

# has a queue of job ids (pops the file after transcription.py returns)

load_dotenv()
app = FastAPI()
queue: list[tuple[str, bytes]] = []
S3_BUCKET: str = "https://s3-aged-water-5651.fly.dev"

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

def _process_queue() -> None:
    """process all jobs that are in queue"""
    while queue:
        jobid, audio_bytes = queue[0]

        try: transcript_bytes: bytes = generate_diarized_transcript(audio_bytes=audio_bytes)
        except Exception as e:
            error_text: str = f"transcription failed for job '{jobid}': {e}"
            transcript_bytes = error_text.encode("utf-8")
        finally: 
            queue.pop(0)

        _post_transcription_to_s3(jobid, transcript_bytes)

@app.post("/upload")
async def upload(file: UploadFile = File(...), jobid: str = Form(...)) -> dict[str, str]:
    """receives an audio blob and a job id, and either forwards the audio to s3 or runs local transcription"""
    audio_bytes: bytes = await file.read()
    queue.append((jobid, audio_bytes))

    if get_transcription_state() != "idle":
        _post_audio_to_s3(jobid, audio_bytes, file.filename)
        return {"jobid": jobid, "status": "queued"}

    _process_queue()
    return {"jobid": jobid, "status": "completed"}

@app.post("/status")
async def get_status(jobid: str) -> dict[str, str]:
    """
    status endpoint
    """
    jobids: list[str] = [queued_jobid for queued_jobid, _ in queue]

    if jobid not in jobids: raise HTTPException(status_code=404, detail="job not found")

    if jobids[0] == jobid: return {"jobid": jobid, "status": get_transcription_state()}

    return {"jobid": jobid, "status": "queued"}

def get_transcription_state() -> str: return get_current_state()
