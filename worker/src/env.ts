export interface Env {
  DB: D1Database;
  BUCKET: R2Bucket;
  JWT_SECRET: string;
  JWT_EXP_SECONDS: string;
}

export type Vars = { email: string | null };

export type AppEnv = { Bindings: Env; Variables: Vars };
