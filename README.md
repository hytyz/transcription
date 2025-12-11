# ytyz transcriber
a small, self-hosted application for diarized audio transcription with a web api, an s3-compatible storage api, authentication, and a reverse-proxy gateway. it exposes http endpoints for uploading audio, tracking transcription status over websocket, storing results in object storage, and managing users with jwt cookies

## services
- gateway: reverse proxy, cors handling, request routing
- auth: user management; pbkdf2 password hashing; rs256 jwt in httponly cookies; users stored in a sqlite db
- transcription: fastapi service that runs whisperx + pyannote for diarization on (only nvidia) gpu; streams status updates over websocket; saves transcripts to s3
- s3: bun server that wraps an s3-compatible endpoint for queue files and transcripts
- frontend: single-page application with client-side routing in vanilla js

## stretch goals:
1. rust ui
2. cli (https://github.com/fastapi/typer)
3. ts everywhere
4. email verification + password change via email + captcha on register (and proper security i guess)