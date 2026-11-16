export interface Env {
  DB: D1Database;
  BUCKET: R2Bucket;
  AUTH_LIMITER: RateLimit;
  UPLOAD_LIMITER: RateLimit;
  JWT_SECRET: string;
  WORKER_TOKEN: string;
  ADMIN_EMAIL: string;
  JWT_EXP_SECONDS: string;
  MAX_UPLOAD_MB: string;
}

export type Vars = { email: string | null };

export type AppEnv = { Bindings: Env; Variables: Vars };
