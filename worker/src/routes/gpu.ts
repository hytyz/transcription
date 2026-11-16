import { Hono } from "hono";
import type { Context } from "hono";
import type { AppEnv } from "../env";
import { logger } from "../logger";
import { requireWorkerToken } from "../middleware";
import { JOBID_RE } from "../ownership";

const PROCESSING = ["received", "transcribing", "aligning", "diarizing", "postprocessing"];
const PROCESSING_SQL = PROCESSING.map((s) => `'${s}'`).join(", ");

const now = () => Math.floor(Date.now() / 1000);

async function activeJob(c: Context<AppEnv>, jobid: string) {
  if (!JOBID_RE.test(jobid)) return null;
  return c.env.DB.prepare(`SELECT jobid FROM jobs WHERE jobid = ? AND status IN (${PROCESSING_SQL})`)
    .bind(jobid)
    .first<{ jobid: string; audio_key: string }>();
}

const gpu = new Hono<AppEnv>();

gpu.use("*", requireWorkerToken);

gpu.post("/claim", async (c) => {
  const job = await c.env.DB.prepare(
    `UPDATE jobs SET status = 'received', updated_at = ?
     WHERE jobid = (SELECT jobid FROM jobs WHERE status = 'queued' ORDER BY created_at LIMIT 1)
     RETURNING jobid, filename`,
  )
    .bind(now())
    .first<{ jobid: string; filename: string }>();

  if (!job) return c.body(null, 204);
  logger.info("job claimed", job);
  return c.json(job);
});

gpu.get("/jobs/:jobid/audio", async (c) => {
  const job = await activeJob(c, c.req.param("jobid"));
  if (!job) return c.json({ error: "job not found" }, 404);

  const obj = await c.env.BUCKET.get(job.audio_key);
  if (!obj) return c.json({ error: "audio not found" }, 404);
  return new Response(obj.body, {
    headers: {
      "Content-Type": obj.httpMetadata?.contentType ?? "application/octet-stream",
      "Content-Length": String(obj.size),
    },
  });
});

export default gpu;
