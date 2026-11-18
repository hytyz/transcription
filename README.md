# ytyz transcriber
a small, self-hosted application for diarized audio transcription. audio is uploaded in the browser, a gpu machine runs whisperx + pyannote on it, and the transcript comes back with speaker labels that can be relabelled, renamed, and downloaded

## services
- worker: cloudflare worker that serves the frontend and the api; pbkdf2 password hashing; hs256 jwt in httponly cookies; users and the job queue in d1; audio and transcripts in r2
- gpu: python script that polls the worker for jobs and runs whisperx + pyannote on an (only nvidia) gpu, reporting status as it goes
- frontend: single-page application with client-side routing in vanilla js

## stretch goals:
1. rust ui
2. cli (https://github.com/fastapi/typer)
3. ts everywhere
4. email verification + password change via email + captcha on register (and proper security i guess)
