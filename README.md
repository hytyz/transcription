# ytyz transcriber
a small, self-hosted application for diarized audio transcription with a web api, an s3-compatible storage api, authentication, and a reverse-proxy gateway. it exposes http endpoints for uploading audio, tracking transcription status over websocket, storing results in object storage, and managing users with jwt cookies

## architecture
- gateway api: reverse proxy for a single origin and cors surface
- auth api: user management; pbkdf2 password hashing; rs256 jwt in httponly cookies; users stored in a sqlite db
- transcription api: fastapi service that runs whisperX + pyannote for diarization on (only nvidia) gpu; streams status updates over websocket; saves transcripts to s3.
- s3 api: bun server that wraps an s3-compatible endpoint for queue files and transcripts

## endpoints
### gateway api
`/`
- proxies:
  - `/auth` to auth api
  - `/api` to transcription api
  - `/s3` to s3 api
  - `/` to the web app
- `GET /__usage`

### auth api
`/auth`
- `POST /create`
- `POST /login`
- `POST /logout`
- `GET /me`
- `POST /increment`
- `GET /usage`
- `GET /myusage`
- `POST /transcriptions/add`
- `DELETE /transcriptions/delete`
- `GET /transcriptions/`

### transcription api
`/api`
- `POST /upload` 
- `WS /ws/status`

### s3 api
`/s3`
- `POST /queue`
- `POST /transcriptions`
- `PUT /transcriptions`
- `GET /queue/:jobid`
- `GET /transcriptions/:jobid`
- `DELETE /transcriptions/:key`

## todo:
1. self host (+ fix the flowchart + write a real readme)
2. finish readme and fix file cards

## stretch goals:
1. rust ui
2. cli (https://github.com/fastapi/typer)
3. ts everywhere
4. email verification + password change via email + captcha on register (and proper security i guess)