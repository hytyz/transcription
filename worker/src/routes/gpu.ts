import { Hono } from "hono";
import type { Context } from "hono";
import type { AppEnv } from "../env";
import { logger } from "../logger";
import { requireWorkerToken } from "../middleware";
import { JOBID_RE, transcriptKey } from "../ownership";

const PROCESSING = ["received", "transcribing", "aligning", "diarizing", "postprocessing"];
const PROCESSING_SQL = PROCESSING.map((s) => `'${s}'`).join(", ");
const MAX_ERROR_LENGTH = 2000;

const now = () => Math.floor(Date.now() / 1000);

async function activeJob(c: Context<AppEnv>, jobid: string) {
  if (!JOBID_RE.test(jobid)) return null;
  return c.env.DB.prepare(`SELECT jobid, audio_key FROM jobs WHERE jobid = ? AND status IN (${PROCESSING_SQL})`)
    .bind(jobid)
    .first<{ jobid: string; audio_key: string }>();
}

async function failJob(c: Context<AppEnv>, jobid: string, audioKey: string, error: string) {
  const message = error.slice(0, MAX_ERROR_LENGTH);
  await c.env.BUCKET.put(transcriptKey(jobid), `transcription failed for job '${jobid}': ${message}`, {
    httpMetadata: { contentType: "text/plain; charset=utf-8" },
  });
  await c.env.BUCKET.delete(audioKey);
  await c.env.DB.prepare("UPDATE jobs SET status = 'error', error = ?, updated_at = ? WHERE jobid = ?")
    .bind(message, now(), jobid)
    .run();
}

const gpu = new Hono<AppEnv>();

gpu.use("*", requireWorkerToken);

gpu.post("/claim", async (c) => {
  const ts = now();
  const staleBefore = ts - parseInt(c.env.STALE_JOB_SECONDS, 10);
  const maxAttempts = parseInt(c.env.MAX_JOB_ATTEMPTS, 10);

  const { results: abandoned } = await c.env.DB.prepare(
    `SELECT jobid, audio_key FROM jobs WHERE status IN (${PROCESSING_SQL}) AND updated_at < ? AND attempts >= ?`,
  )
    .bind(staleBefore, maxAttempts)
    .all<{ jobid: string; audio_key: string }>();
  for (const job of abandoned) {
    logger.warn("giving up on job", { jobid: job.jobid, attempts: maxAttempts });
    await failJob(c, job.jobid, job.audio_key, `gave up after ${maxAttempts} attempts`);
  }

  const job = await c.env.DB.prepare(
    `UPDATE jobs SET status = 'received', attempts = attempts + 1, error = NULL, updated_at = ?
     WHERE jobid = (
       SELECT jobid FROM jobs
       WHERE status = 'queued' OR (status IN (${PROCESSING_SQL}) AND updated_at < ?)
       ORDER BY created_at LIMIT 1
     )
     RETURNING jobid, filename, attempts`,
  )
    .bind(ts, staleBefore)
    .first<{ jobid: string; filename: string; attempts: number }>();

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

gpu.post("/jobs/:jobid/status", async (c) => {
  const jobid = c.req.param("jobid");
  const { status } = await c.req.json<{ status?: string }>().catch(() => ({}) as { status?: undefined });
  if (!status || !PROCESSING.includes(status)) return c.json({ error: "invalid status" }, 400);
  if (!(await activeJob(c, jobid))) return c.json({ error: "job not found" }, 404);

  await c.env.DB.prepare("UPDATE jobs SET status = ?, updated_at = ? WHERE jobid = ?").bind(status, now(), jobid).run();
  return c.json({ ok: true });
});

gpu.post("/jobs/:jobid/complete", async (c) => {
  const jobid = c.req.param("jobid");
  const job = await activeJob(c, jobid);
  if (!job) return c.json({ error: "job not found" }, 404);

  const transcript = await c.req.arrayBuffer();
  await c.env.BUCKET.put(transcriptKey(jobid), transcript, {
    httpMetadata: { contentType: "text/plain; charset=utf-8" },
  });
  await c.env.BUCKET.delete(job.audio_key);
  await c.env.DB.prepare("UPDATE jobs SET status = 'completed', updated_at = ? WHERE jobid = ?").bind(now(), jobid).run();

  logger.info("job completed", { jobid, size: transcript.byteLength });
  return c.json({ ok: true });
});

gpu.post("/jobs/:jobid/fail", async (c) => {
  const jobid = c.req.param("jobid");
  const job = await activeJob(c, jobid);
  if (!job) return c.json({ error: "job not found" }, 404);

  const { error } = await c.req.json<{ error?: string }>().catch(() => ({}) as { error?: undefined });
  await failJob(c, jobid, job.audio_key, error || "unknown error");

  logger.warn("job failed", { jobid, error });
  return c.json({ ok: true });
});

export default gpu;
