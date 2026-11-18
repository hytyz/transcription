export interface Env {
  DB: D1Database;
  BUCKET: R2Bucket;
  ASSETS: Fetcher;
  AUTH_LIMITER: RateLimit;
  UPLOAD_LIMITER: RateLimit;
  JWT_SECRET: string;
  WORKER_TOKEN: string;
  JWT_EXP_SECONDS: string;
  MAX_UPLOAD_MB: string;
  STALE_JOB_SECONDS: string;
  MAX_JOB_ATTEMPTS: string;
}

export type Vars = { email: string | null };

export type AppEnv = { Bindings: Env; Variables: Vars };
