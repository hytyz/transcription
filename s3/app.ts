import {
  S3Client,
  PutObjectCommand,
  GetObjectCommand,
  DeleteObjectCommand,
} from "@aws-sdk/client-s3";
import dotenv from "dotenv";
import { logger } from "./logger";
dotenv.config();
declare const Bun: any;

const requiredEnvVars = ["AWS_REGION", "AWS_ENDPOINT_URL", "BUCKET_NAME", "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY"];
for (const envVar of requiredEnvVars) {
  if (!process.env[envVar]) {
    throw new Error(`missing required environment variable: ${envVar}`);
  }
}

logger.info("initializing s3 client", { 
  region: process.env.AWS_REGION, 
  endpoint: process.env.AWS_ENDPOINT_URL,
  bucket: process.env.BUCKET_NAME 
});

/**
 * aws s3 compatible client
 * endpoint and credentials come from environment variables
 */
const s3 = new S3Client({
  region: process.env.AWS_REGION!,
  endpoint: process.env.AWS_ENDPOINT_URL!,
  forcePathStyle: false,
  credentials: {
    accessKeyId: process.env.AWS_ACCESS_KEY_ID!,
    secretAccessKey: process.env.AWS_SECRET_ACCESS_KEY!,
  },
});

const BUCKET = process.env.BUCKET_NAME!;

/**
 * sanitises a string to be safe for use in s3 keys
 * removes path traversal attempts, null bytes, and special characters
 * @param input raw string from user input
 * @returns sanitised string safe for S3 keys
 */
function sanitiseForS3Key(input: string): string {
  return input
    .replace(/\.\./g, "")        // remove path traversal
    .replace(/\0/g, "")          // remove null bytes
    .replace(/[\/\\]/g, "")      // remove slashes
    .replace(/[^a-zA-Z0-9._-]/g, "_") // replace other special chars with underscore
    .slice(0, 255);              // limit length
}

/**
 * extracts and sanitises file extension
 * @param filename original filename
 * @returns sanitised extension or "bin" as fallback
 */
function sanitiseExtension(filename: string): string {
  const ext = filename.split(".").pop() ?? "bin";
  // only allow alphanumeric extensions, max 10 chars
  const sanitised = ext.replace(/[^a-zA-Z0-9]/g, "").slice(0, 10);
  return sanitised || "bin";
}


/**
 * returns json with a status code
 * @param obj payload
 * @param status http status code
 */
function json(obj: any, status = 200) {
  return new Response(JSON.stringify(obj), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

/**
 * bun http server that exposes an object api
 *
 * POST   /queue
 * upload a media file as queue/{jobid}.{ext}
 * GET    /queue/:jobid
 * fetch the first matching queued media by known extensions
 *
 * POST   /transcriptions
 * create a transcription text as transcriptions/{jobid}.txt
 * PUT    /transcriptions
 * update an existing transcription in place
 * GET    /transcriptions/:jobid
 * fetch transcription text
 * DELETE /transcriptions/:jobid
 * delete by job id
 * DELETE /transcriptions?key=
 * delete by explicit key. accepts either full key or filename
 */
const app = Bun.serve({
  port: 6767,
  async fetch(req: Request) {
    const startTime = Date.now();
    const url = new URL(req.url);
    const pathname = url.pathname;
    
    logger.request(req.method, pathname);

    // POST /queue  — upload audio file under {jobid}.{ext}
    if (req.method === "POST" && pathname === "/queue") {
      const form = await req.formData();
      const file = form.get("file") as File | null;
      const jobid = form.get("jobid") as string | null;

      if (!file || !jobid) {
        logger.warn("bad request: missing file or jobid", { path: pathname });
        return json(
          { status: "error", message: "file and jobid required" },
          400
        );
      }

      const sanitisedJobid = sanitiseForS3Key(jobid);
      const ext = sanitiseExtension(file.name);
      const key = `queue/${sanitisedJobid}.${ext}`;
      const fileSize = file.size;

      logger.s3Operation("PUT", key, { jobid: sanitisedJobid, fileSize, contentType: file.type });
      
      await s3.send(
        new PutObjectCommand({
          Bucket: BUCKET,
          Key: key,
          Body: new Uint8Array(await file.arrayBuffer()),
          ContentType: file.type || "application/octet-stream",
        })
      );

      logger.response(req.method, pathname, 200, Date.now() - startTime, { key, fileSize });
      return json({ status: "ok", jobid, key });
    }

    // POST /transcriptions
    if (req.method === "POST" && pathname === "/transcriptions") {
      const form = await req.formData();
      const file = form.get("file") as File | null;
      const jobid = form.get("jobid") as string | null;

      if (!file || !jobid) {
        logger.warn("bad request: missing file or jobid", { path: pathname });
        return json(
          { status: "error", message: "file and jobid required" },
          400
        );
      }

      const sanitisedJobid = sanitiseForS3Key(jobid);
      const key = `transcriptions/${sanitisedJobid}.txt`;
      const fileSize = file.size;
      
      logger.s3Operation("PUT", key, { jobid: sanitisedJobid, fileSize });
      await s3.send(
        new PutObjectCommand({
          Bucket: BUCKET,
          Key: key,
          Body: new Uint8Array(await file.arrayBuffer()),
          ContentType: "text/plain",
        })
      );

      logger.response(req.method, pathname, 200, Date.now() - startTime, { key });
      return json({ status: "ok", jobid, key });
    }

    // GET /queue/:jobid
    const qMatch = pathname.match(/^\/queue\/(.+)$/);
    if (req.method === "GET" && qMatch) {
      const jobid = qMatch[1];
      logger.debug("fetching queued audio", { jobid });

      const exts = ["wav", "mp3", "m4a", "flac", "ogg", "bin"];

      for (const ext of exts) {
        const Key = `queue/${jobid}.${ext}`;
        try {
          logger.s3Operation("GET", Key);
          const res = await s3.send(
            new GetObjectCommand({ Bucket: BUCKET, Key })
          );
          logger.response(req.method, pathname, 200, Date.now() - startTime, { key: Key });
          return new Response(res.Body as any, {
            headers: {
              "Content-Type": res.ContentType || "application/octet-stream",
              "Content-Disposition": `attachment; filename="${jobid}.${ext}"`,
            },
          });
        } catch (err: any) {
          // NoSuchKey is expected when trying different extensions, otherwise log
          if (err.name !== "NoSuchKey") {
            logger.error("s3 fetch error", { key: Key, error: err.message });
          }
        }
      }

      logger.response(req.method, pathname, 404, Date.now() - startTime, { jobid });
      return json({ status: "error", message: "file not found" }, 404);
    }

    // PUT /transcriptions
    if (req.method === "PUT" && pathname.startsWith("/transcriptions")) {
      const form = await req.formData();
      const file = form.get("file") as File | null;
      const jobid = form.get("jobid") as string | null;

      if (!file || !jobid) {
        logger.warn("bad request: missing file or jobid", { path: pathname });
        return json(
          { status: "error", message: "file and jobid required" },
          400
        );
      }

      const sanitisedJobid = sanitiseForS3Key(jobid);
      const key = `transcriptions/${sanitisedJobid}.txt`;
      const fileSize = file.size;
      
      logger.s3Operation("PUT", key, { jobid: sanitisedJobid, fileSize, update: true });
      await s3.send(
        new PutObjectCommand({
          Bucket: BUCKET,
          Key: key,
          Body: new Uint8Array(await file.arrayBuffer()),
          ContentType: "text/plain",
        })
      );

      logger.response(req.method, pathname, 200, Date.now() - startTime, { key });
      return json({ status: "ok", jobid, key, message: "updated in place" });
    }

    // DELETE /transcriptions/:jobid
    if (req.method === "DELETE" && pathname.startsWith("/transcriptions")) {
      const m = pathname.match(/^\/transcriptions\/([^/]+)$/);
      let Key: string | null = null;
      const rawKey = url.searchParams.get("key");

      if (rawKey && rawKey.trim() !== "") {
        Key = rawKey.startsWith("transcriptions/") ? rawKey : `transcriptions/${rawKey}`;
      } else if (m) {
        const jobid = m[1];
        Key = `transcriptions/${jobid}.txt`;
      } else {
        return json({ status: "error", message: "bad path" }, 400);
      }

      logger.s3Operation("DELETE", Key);
      try {
        await s3.send(new DeleteObjectCommand({ Bucket: BUCKET, Key }));
        logger.response(req.method, pathname, 200, Date.now() - startTime, { key: Key });
        return json({ status: "ok", message: "file deleted successfully" });
      } catch (err: any) {
        logger.error("s3 delete error", { key: Key, error: err.message });
        logger.response(req.method, pathname, 404, Date.now() - startTime, { key: Key });
        return json({ status: "error", message: "file not found" }, 404);
      }
    }

    // GET /transcriptions/:jobid
    const tMatch = pathname.match(/^\/transcriptions\/(.+)$/);
    if (req.method === "GET" && tMatch) {
      const jobid = tMatch[1];
      const Key = `transcriptions/${jobid}.txt`;

      logger.s3Operation("GET", Key, { jobid });
      try {
        const res = await s3.send(
          new GetObjectCommand({ Bucket: BUCKET, Key })
        );
        logger.response(req.method, pathname, 200, Date.now() - startTime, { key: Key });
        return new Response(res.Body as any, {
          headers: { "Content-Type": "text/plain" },
        });
      } catch (err: any) {
        if (err.name !== "NoSuchKey") {
          logger.error("s3 fetch error", { key: Key, error: err.message });
        }
        logger.response(req.method, pathname, 404, Date.now() - startTime, { key: Key });
        return json({ status: "error", message: "file not found" }, 404);
      }
    }

    logger.warn("route not found", { method: req.method, path: pathname });
    return json({ status: "error", message: "not found" }, 404);
  },
});

logger.info("server started", { port: app.port });
