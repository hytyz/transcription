import { Hono } from "hono";
import type { Context } from "hono";
import type { AppEnv } from "../env";
import { logger } from "../logger";
import { csrf, rateLimit } from "../middleware";
import { JOBID_RE, canAccess } from "../ownership";

const PART_SIZE = 50 * 1024 * 1024;
const MAX_PARTS = 10_000;

type JobRow = {
  jobid: string;
  email: string | null;
  filename: string;
  audio_key: string;
  upload_id: string | null;
  status: string;
  error: string | null;
  created_at: number;
};

const now = () => Math.floor(Date.now() / 1000);

function sanitiseFilename(name: string) {
  const cleaned = name
    .replace(/\.{2,}/g, "")
    .replace(/[\/\\\0]/g, "")
    .replace(/[^a-zA-Z0-9._ -]/g, "_")
    .slice(0, 255);
  return cleaned || "audio";
}

function sanitiseExtension(filename: string) {
  const ext = filename.includes(".") ? filename.split(".").pop()! : "bin";
  return ext.replace(/[^a-zA-Z0-9]/g, "").slice(0, 10).toLowerCase() || "bin";
}

async function loadUploadingJob(c: Context<AppEnv>, jobid: string) {
  if (!JOBID_RE.test(jobid)) return null;
  const job = await c.env.DB.prepare("SELECT * FROM jobs WHERE jobid = ?").bind(jobid).first<JobRow>();
  if (!job || job.status !== "uploading" || !job.upload_id) return null;
  if (job.email !== null && job.email !== c.get("email")) return null;
  return job;
}

const jobs = new Hono<AppEnv>();

jobs.post("/upload/start", csrf, rateLimit("UPLOAD_LIMITER"), async (c) => {
  const body = await c.req
    .json<{ filename?: unknown; size?: unknown; contentType?: unknown }>()
    .catch(() => ({}) as Record<string, unknown>);
  const size = Number(body.size);
  const maxBytes = parseInt(c.env.MAX_UPLOAD_MB, 10) * 1024 * 1024;

  if (typeof body.filename !== "string" || !Number.isFinite(size) || size <= 0) {
    return c.json({ error: "filename and size required" }, 400);
  }
  if (size > maxBytes) return c.json({ error: `file is larger than ${c.env.MAX_UPLOAD_MB} MB` }, 413);

  const jobid = crypto.randomUUID();
  const filename = sanitiseFilename(body.filename);
  const audioKey = `queue/${jobid}.${sanitiseExtension(filename)}`;
  const contentType = typeof body.contentType === "string" && body.contentType ? body.contentType : "application/octet-stream";

  const upload = await c.env.BUCKET.createMultipartUpload(audioKey, { httpMetadata: { contentType } });
  const ts = now();
  await c.env.DB.prepare(
    "INSERT INTO jobs(jobid, email, filename, audio_key, upload_id, status, created_at, updated_at) VALUES(?, ?, ?, ?, ?, 'uploading', ?, ?)",
  )
    .bind(jobid, c.get("email"), filename, audioKey, upload.uploadId, ts, ts)
    .run();

  logger.info("upload started", { jobid, size, email: c.get("email") });
  return c.json({ jobid, partSize: PART_SIZE });
});

jobs.put("/upload/:jobid/:part", csrf, async (c) => {
  const partNumber = parseInt(c.req.param("part"), 10);
  if (!Number.isInteger(partNumber) || partNumber < 1 || partNumber > MAX_PARTS) {
    return c.json({ error: "invalid part number" }, 400);
  }
  const job = await loadUploadingJob(c, c.req.param("jobid"));
  if (!job) return c.json({ error: "upload not found" }, 404);
  if (!c.req.raw.body) return c.json({ error: "empty body" }, 400);

  const upload = c.env.BUCKET.resumeMultipartUpload(job.audio_key, job.upload_id!);
  const part = await upload.uploadPart(partNumber, c.req.raw.body);
  return c.json({ partNumber: part.partNumber, etag: part.etag });
});

jobs.post("/upload/:jobid/complete", csrf, async (c) => {
  const job = await loadUploadingJob(c, c.req.param("jobid"));
  if (!job) return c.json({ error: "upload not found" }, 404);

  const { parts } = await c.req.json<{ parts?: R2UploadedPart[] }>().catch(() => ({}) as { parts?: undefined });
  if (!Array.isArray(parts) || parts.length === 0) return c.json({ error: "parts required" }, 400);

  const upload = c.env.BUCKET.resumeMultipartUpload(job.audio_key, job.upload_id!);
  try {
    await upload.complete(parts.map((p) => ({ partNumber: Number(p.partNumber), etag: String(p.etag) })));
  } catch (err) {
    logger.error("multipart complete failed", { jobid: job.jobid, error: (err as Error).message });
    return c.json({ error: "upload could not be completed" }, 400);
  }

  const ts = now();
  const statements = [
    c.env.DB.prepare("UPDATE jobs SET status = 'queued', upload_id = NULL, created_at = ?, updated_at = ? WHERE jobid = ?").bind(
      ts,
      ts,
      job.jobid,
    ),
  ];
  if (job.email) {
    statements.push(
      c.env.DB.prepare("INSERT INTO transcriptions(jobid, email, created_at, filename) VALUES(?, ?, ?, ?)").bind(
        job.jobid,
        job.email,
        ts,
        job.filename,
      ),
      c.env.DB.prepare("UPDATE users SET api_usage = api_usage + 1 WHERE email = ?").bind(job.email),
    );
  }
  await c.env.DB.batch(statements);

  logger.info("job queued", { jobid: job.jobid, email: job.email });
  return c.json({ jobid: job.jobid, status: "queued" });
});

jobs.get("/jobs/:jobid", async (c) => {
  const jobid = c.req.param("jobid");
  if (!(await canAccess(c, jobid))) return c.json({ error: "job not found" }, 404);

  const job = await c.env.DB.prepare("SELECT jobid, status, error, created_at FROM jobs WHERE jobid = ?")
    .bind(jobid)
    .first<Pick<JobRow, "jobid" | "status" | "error" | "created_at">>();
  if (!job) return c.json({ jobid, status: "completed" });

  let ahead = 0;
  if (job.status === "queued") {
    const row = await c.env.DB.prepare("SELECT COUNT(*) AS n FROM jobs WHERE status = 'queued' AND created_at < ?")
      .bind(job.created_at)
      .first<{ n: number }>();
    ahead = row?.n ?? 0;
  }
  return c.json({ jobid, status: job.status, error: job.error, ahead });
});

export default jobs;
