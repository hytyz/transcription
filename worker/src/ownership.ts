import type { Context } from "hono";
import type { AppEnv } from "./env";

export const JOBID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;

export const transcriptKey = (jobid: string) => `transcriptions/${jobid}.txt`;

type Owner = { found: false } | { found: true; email: string | null };

export async function findOwner(c: Context<AppEnv>, jobid: string): Promise<Owner> {
  const row = await c.env.DB.prepare("SELECT email FROM transcriptions WHERE jobid = ?")
    .bind(jobid)
    .first<{ email: string }>();
  if (row) return { found: true, email: row.email };

  return { found: false };
}

export async function canAccess(c: Context<AppEnv>, jobid: string) {
  if (!JOBID_RE.test(jobid)) return false;
  const owner = await findOwner(c, jobid);
  if (!owner.found) return false;
  return owner.email === null || owner.email === c.get("email");
}
