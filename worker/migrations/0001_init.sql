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
