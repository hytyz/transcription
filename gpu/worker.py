import json; import logging; import os; import tempfile; import time
from datetime import datetime; from enum import Enum; from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()

from module import generate_diarized_transcript, warm_up

class JSONFormatter(logging.Formatter):
    def format(self, record):
        log_obj = {
            "timestamp": datetime.now().isoformat(),
            "level": record.levelname.lower(),
            "service": "gpu",
            "message": record.getMessage(),
        }
        if hasattr(record, "extra_data"): log_obj.update(record.extra_data)
        return json.dumps(log_obj)

logger = logging.getLogger("gpu")
logger.setLevel(logging.DEBUG if os.environ.get("LOG_LEVEL") == "debug" else logging.INFO)
handler = logging.StreamHandler()
handler.setFormatter(JSONFormatter())
logger.handlers = [handler]

def log_with_extra(level, message, **kwargs):
    record = logging.LogRecord(name="gpu", level=level, pathname="", lineno=0, msg=message, args=(), exc_info=None)
    record.extra_data = kwargs
    logger.handle(record)

API_URL = os.environ["API_URL"].rstrip("/")
WORKER_TOKEN = os.environ["WORKER_TOKEN"]
POLL_INTERVAL = float(os.environ.get("POLL_INTERVAL", "5"))
MAX_BACKOFF = 60.0

session = requests.Session()
session.headers.update({"Authorization": f"Bearer {WORKER_TOKEN}", "User-Agent": "transcription-gpu-worker"})

def _api(method, path, timeout=30, **kwargs):
    resp = session.request(method, f"{API_URL}/api/worker{path}", timeout=timeout, **kwargs)
    resp.raise_for_status()
    return resp

class StatusReporter:
    def __init__(self, jobid):
        self.jobid = jobid
        self.status = "received"

    def set(self, status):
        self.status = status.value if isinstance(status, Enum) else str(status)
        self._send()

    def _send(self):
        try: _api("POST", f"/jobs/{self.jobid}/status", json={"status": self.status})
        except requests.RequestException as e: log_with_extra(logging.WARNING, "status update failed", jobid=self.jobid, status=self.status, error=str(e))

def _download_audio(jobid, path):
    size = 0
    with _api("GET", f"/jobs/{jobid}/audio", timeout=300, stream=True) as resp, open(path, "wb") as f:
        for chunk in resp.iter_content(chunk_size=1024 * 1024):
            f.write(chunk)
            size += len(chunk)
    return size

def process(job: dict):
    jobid = job["jobid"]
    suffix = Path(job.get("filename") or "").suffix or ".audio"
    fd, path = tempfile.mkstemp(suffix=suffix)
    os.close(fd)
    started = time.monotonic()
    log_with_extra(logging.INFO, "processing job", jobid=jobid, attempt=job.get("attempts"))

    try:
        reporter = StatusReporter(jobid)
        size = _download_audio(jobid, path)
        log_with_extra(logging.DEBUG, "audio downloaded", jobid=jobid, size=size)
        transcript: bytes = generate_diarized_transcript(path, on_status=reporter.set)
        _api("POST", f"/jobs/{jobid}/complete", timeout=120, data=transcript, headers={"Content-Type": "text/plain; charset=utf-8"})
        log_with_extra(logging.INFO, "job completed", jobid=jobid, transcript_size=len(transcript), seconds=round(time.monotonic() - started, 1))
    except requests.RequestException as e:
        log_with_extra(logging.ERROR, "network error while processing job, it will be retried", jobid=jobid, error=str(e))
    except Exception as e:
        log_with_extra(logging.ERROR, "job failed", jobid=jobid, error=str(e))
        try: _api("POST", f"/jobs/{jobid}/fail", json={"error": str(e)})
        except requests.RequestException as report_error:
            log_with_extra(logging.ERROR, "could not report failure", jobid=jobid, error=str(report_error))

def main():
    log_with_extra(logging.INFO, "loading models")
    warm_up()
    log_with_extra(logging.INFO, "gpu worker started", api_url=API_URL, poll_interval=POLL_INTERVAL)

    failures = 0
    while True:
        try:
            resp = _api("POST", "/claim")
            failures = 0
            if resp.status_code == 204: time.sleep(POLL_INTERVAL); continue
            process(resp.json())
        except requests.RequestException as e:
            failures += 1
            delay = min(POLL_INTERVAL * 2 ** failures, MAX_BACKOFF)
            log_with_extra(logging.WARNING, "could not reach api", error=str(e), retry_in=delay)
            time.sleep(delay)

if __name__ == "__main__":
    try: main()
    except KeyboardInterrupt: log_with_extra(logging.INFO, "gpu worker stopped")
