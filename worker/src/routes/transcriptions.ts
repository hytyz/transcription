import { Hono } from "hono";
import type { AppEnv } from "../env";
import { logger } from "../logger";
import { requireAuth } from "../middleware";
import { canAccess, transcriptKey } from "../ownership";

const MAX_TRANSCRIPT_BYTES = 5 * 1024 * 1024;
const FILENAME_RE = /^[A-Za-z0-9 _\-.]{1,255}$/;

export const transcriptions = new Hono<AppEnv>();

transcriptions.use("*", requireAuth);

transcriptions.get("/", async (c) => {
  const email = c.get("email")!;
  const { results } = await c.env.DB.prepare(
    "SELECT jobid, created_at, filename FROM transcriptions WHERE email = ? ORDER BY created_at DESC",
  )
    .bind(email)
    .all();
  return c.json({ email, transcriptions: results });
});

transcriptions.put("/rename", async (c) => {
  const email = c.get("email")!;
  const { jobid, filename } = await c.req.json<{ jobid?: string; filename?: string }>().catch(() => ({}) as Record<string, undefined>);
  if (!jobid || !filename) return c.json({ error: "jobid and filename required" }, 400);
  if (!FILENAME_RE.test(filename)) return c.json({ error: "invalid filename" }, 400);

  const result = await c.env.DB.prepare("UPDATE transcriptions SET filename = ? WHERE jobid = ? AND email = ?")
    .bind(filename, jobid, email)
    .run();
  if (result.meta.changes === 0) return c.json({ error: "transcription not found" }, 404);

  logger.info("transcription renamed", { jobid, email });
  return c.json({ ok: true, jobid, filename });
});

transcriptions.delete("/delete", async (c) => {
  const email = c.get("email")!;
  const { jobid } = await c.req.json<{ jobid?: string }>().catch(() => ({}) as Record<string, undefined>);
  if (!jobid) return c.json({ error: "jobid required" }, 400);

  const result = await c.env.DB.prepare("DELETE FROM transcriptions WHERE jobid = ? AND email = ?")
    .bind(jobid, email)
    .run();
  if (result.meta.changes === 0) return c.json({ error: "transcription not found" }, 404);

  logger.info("transcription deleted", { jobid, email });
  return c.json({ ok: true, jobid });
});

export const files = new Hono<AppEnv>();

files.get("/transcriptions/:jobid", async (c) => {
  const jobid = c.req.param("jobid");
  if (!(await canAccess(c, jobid))) return c.json({ status: "error", message: "file not found" }, 404);

  const obj = await c.env.BUCKET.get(transcriptKey(jobid));
  if (!obj) return c.json({ status: "error", message: "file not found" }, 404);

  return new Response(obj.body, {
    headers: { "Content-Type": "text/plain; charset=utf-8", "Cache-Control": "private, no-store" },
  });
});

files.put("/transcriptions", async (c) => {
  const form = await c.req.formData().catch(() => null);
  const jobid = form?.get("jobid");
  const file = form?.get("file");
  if (typeof jobid !== "string" || !(file instanceof File)) {
    return c.json({ status: "error", message: "file and jobid required" }, 400);
  }
  if (file.size > MAX_TRANSCRIPT_BYTES) return c.json({ status: "error", message: "file too large" }, 413);
  if (!(await canAccess(c, jobid))) return c.json({ status: "error", message: "file not found" }, 404);

  const existing = await c.env.BUCKET.head(transcriptKey(jobid));
  if (!existing) return c.json({ status: "error", message: "file not found" }, 404);

  await c.env.BUCKET.put(transcriptKey(jobid), await file.arrayBuffer(), {
    httpMetadata: { contentType: "text/plain; charset=utf-8" },
  });

  logger.info("transcription updated", { jobid });
  return c.json({ status: "ok", jobid, message: "updated in place" });
});
