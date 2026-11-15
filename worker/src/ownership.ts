import type { Context } from "hono";
import type { AppEnv } from "./env";

export const JOBID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;

export const transcriptKey = (jobid: string) => `transcriptions/${jobid}.txt`;

type Owner = { found: false } | { found: true; email: string | null };

export async function findOwner(c: Context<AppEnv>, jobid: string): Promise<Owner> {
  const job = await c.env.DB.prepare("SELECT email FROM jobs WHERE jobid = ?")
    .bind(jobid)
    .first<{ email: string | null }>();
  if (job) return { found: true, email: job.email };

  const legacy = await c.env.DB.prepare("SELECT email FROM transcriptions WHERE jobid = ?")
    .bind(jobid)
    .first<{ email: string }>();
  if (legacy) return { found: true, email: legacy.email };

  return { found: false };
}

export async function canAccess(c: Context<AppEnv>, jobid: string) {
  if (!JOBID_RE.test(jobid)) return false;
  const owner = await findOwner(c, jobid);
  if (!owner.found) return false;
  return owner.email === null || owner.email === c.get("email");
}
