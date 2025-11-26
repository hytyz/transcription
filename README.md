# ytyz transcriber
a small, self-hosted application for diarized audio transcription with a web api, an s3-compatible storage api, authentication, and a reverse-proxy gateway. it exposes http endpoints for uploading audio, tracking transcription status over websocket, storing results in object storage, and managing users with jwt cookies

## architecture
- gateway api: reverse proxy for a single origin and cors surface
- auth api: user management; pbkdf2 password hashing; rs256 jwt in httponly cookies; users stored in a sqlite db
- transcription api: fastapi service that runs whisperx + pyannote for diarization on (only nvidia) gpu; streams status updates over websocket; saves transcripts to s3
- s3 api: bun server that wraps an s3-compatible endpoint for queue files and transcripts

## stretch goals:
1. rust ui
2. cli (https://github.com/fastapi/typer)
3. ts everywhere
4. email verification + password change via email + captcha on register (and proper security i guess)