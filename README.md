# ytyz transcriber
a small, self-hosted application for diarized audio transcription with a web API, an S3-compatible storage API, authentication, and a reverse-proxy gateway. it exposes HTTP endpoints for uploading audio, tracking transcription status over websocket, storing results in object storage, and managing users with JWT cookies

## architecture
- gateway API: reverse proxy for a single origin and CORS surface
- auth API: user management; PBKDF2 password hashing; RS256 JWT in httponly cookies; users stored in a sqlite db
- transcription API: FastAPI service that runs whisperX + pyannote for diarization on (only nvidia) GPU; streams status updates over websocket; saves transcripts to S3.
- S3 API: bun server that wraps an S3-compatible endpoint for queue files and transcripts

## endpoints
### gateway API
`/`
- proxies:
  - `/auth` to auth API
  - `/api` to transcription API
  - `/s3` to S3 API
  - `/` to the web app
- `GET /__usage`

### auth API
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

### transcription API
`/api`
- `POST /upload` 
- `WS /ws/status`

### S3 API
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