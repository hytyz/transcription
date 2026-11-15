CREATE TABLE IF NOT EXISTS users (
    email TEXT PRIMARY KEY,
    password_hash TEXT NOT NULL,
    salt TEXT NOT NULL,
    api_usage INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS transcriptions (
    jobid TEXT PRIMARY KEY,
    email TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    filename TEXT,
    FOREIGN KEY(email) REFERENCES users(email) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_transcriptions_email ON transcriptions(email, created_at);

CREATE TABLE IF NOT EXISTS jobs (
    jobid TEXT PRIMARY KEY,
    email TEXT,
    filename TEXT NOT NULL,
    audio_key TEXT NOT NULL,
    upload_id TEXT,
    status TEXT NOT NULL,
    error TEXT,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status, created_at);
