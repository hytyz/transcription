import requests; from requests import Response
from transcription import generate_diarized_transcript, get_current_state
from dotenv import load_dotenv; from fastapi import FastAPI
from fastapi import FastAPI, UploadFile, HTTPException

from transcription import generate_diarized_transcript, get_current_state

queue: list = []
current_file: bytes = bytes()
transcript_bytes: bytes = bytes()
S3_BUCKET: str = "https://s3-aged-water-5651.fly.dev/"

# + receives audio files from gateway (from a client POST) and from s3 bucket's /transcriptions
# + POSTs the audio file to s3 bucket's /queue if currently transcribing (get_status from transcription.py) or received return from transcription_py 
# + POSTs the text file (return from transcription.py) to s3 bucket's /transcriptions endpoint for audio files /queue that exists on s3
# + POSTs the return from transcription.py to /transcriptions
# + has an endpoint for status /status (looks at the queue and if first in queue => get_status from transcription.py elif not in queue => return 404) 
# + if transcription.py throws an exception POSTs the error message to /transcription

# has a queue of job ids (pops the file after transcription.py returns)

load_dotenv()
app = FastAPI()

def _process_queue() -> None:
    if not queue: return
    global current_file
    global transcript_bytes
    
    jobid: str = queue[0]
    try: 
        transcript_bytes: bytes = generate_diarized_transcript(audio_bytes=current_file)
        _post_transcription_to_s3(jobid, transcript_bytes)
    except Exception as e: transcript_bytes = bytes(e)

    if queue and queue[0] == jobid: queue.pop(0)

def _post_audio_to_s3(jobid: str, audio_bytes: bytes) -> None:
    data: dict[str, bytes] = {"jobid": jobid, "file": audio_bytes}

    resp: Response = requests.post(f"{S3_BUCKET}/queue", data=data)
    resp.raise_for_status()

def _post_transcription_to_s3(jobid: str, transcript_bytes: bytes) -> None:
    data: dict[str, bytes] = {"jobid": jobid, "file": transcript_bytes}

    resp: Response = requests.post(f"{S3_BUCKET}/queue", data=data)
    resp.raise_for_status()

@app.post("/upload")
async def upload(file: UploadFile, jobid: str) -> dict[str, str]:
    """
    endpoint for other services to POST audio files
    """
    global current_file

    data: bytes = await file.read()
    current_state: str = get_current_state()

    if jobid not in queue: queue.append(jobid)

    if current_state != "idle":
        _post_audio_to_s3(jobid, data)
        return {"jobid": jobid, "status": "queued"}
    
    current_file = data
    _process_queue() # WHEN SHOULD I CALL THIS
    data: dict[str, str] = {"jobid": jobid}

    return {"jobid": jobid, "status": "queued"}


@app.post("/status")
async def get_status(jobid: str) -> dict[str, str]:
    """
    status endpoint
    """
    if jobid in queue:
        if queue[0] == jobid: return {"jobid": jobid, "status": "processing", "pipeline_state": get_current_state()}
        return {"jobid": jobid, "status": "queued"}

    raise HTTPException(status_code=404, detail="job not found")


@app.post("/transcriptions")
async def get_transcription() -> str:
    """
    returns the transcription text for a completed job
    """
    global transcript_bytes
    if transcript_bytes is None: raise HTTPException(status_code=404, detail="transcription not found")
    return transcript_bytes.decode("utf-8")

async def get_transcription_state() -> str: return get_current_state()
