import {
  S3Client,
  PutObjectCommand,
  GetObjectCommand,
  DeleteObjectCommand,
} from "@aws-sdk/client-s3";
import dotenv from "dotenv";
import path from "path";
dotenv.config();

//config
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

function json(obj: any, status = 200) {
  return new Response(JSON.stringify(obj), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

//server
const app = Bun.serve({
  port: 8080,
  async fetch(req) {
    const url = new URL(req.url);
    const pathname = url.pathname;
    // POST /queue  — upload audio file under {jobid}.{ext}
    if (req.method === "POST" && pathname === "/queue") {
      const form = await req.formData();
      const file = form.get("file") as File | null;
      const jobid = form.get("jobid") as string | null;

      if (!file || !jobid) {
        return json(
          { status: "error", message: "file and jobid required" },
          400
        );
      }

      const ext = file.name.split(".").pop() ?? "bin";
      const key = `queue/${jobid}.${ext}`;

      await s3.send(
        new PutObjectCommand({
          Bucket: BUCKET,
          Key: key,
          Body: new Uint8Array(await file.arrayBuffer()),
          ContentType: file.type || "application/octet-stream",
        })
      );

      return json({ status: "ok", jobid, key });
    }

    // POST /transcriptions — upload txt file under {jobid}.txt
    if (req.method === "POST" && pathname === "/transcriptions") {
      const form = await req.formData();
      const file = form.get("file") as File | null;
      const jobid = form.get("jobid") as string | null;

      if (!file || !jobid) {
        return json(
          { status: "error", message: "file and jobid required" },
          400
        );
      }

      const key = `transcriptions/${jobid}.txt`;
      console.log("PUT transcription", { jobid, key });
      await s3.send(
        new PutObjectCommand({
          Bucket: BUCKET,
          Key: key,
          Body: new Uint8Array(await file.arrayBuffer()),
          ContentType: "text/plain",
        })
      );

      return json({ status: "ok", jobid, key });
    }

    // GET /queue/:jobid — return audio file
    const qMatch = pathname.match(/^\/queue\/(.+)$/);
    if (req.method === "GET" && qMatch) {
      const jobid = qMatch[1];

      const exts = ["wav", "mp3", "m4a", "flac", "ogg", "bin"];

      for (const ext of exts) {
        const Key = `queue/${jobid}.${ext}`;
        try {
          const res = await s3.send(
            new GetObjectCommand({ Bucket: BUCKET, Key })
          );
          return new Response(res.Body as any, {
            headers: {
              "Content-Type": res.ContentType || "application/octet-stream",
              "Content-Disposition": `attachment; filename="${jobid}.${ext}"`,
            },
          });
        } catch {
          // ignore, try next
        }
      }

      return json({ status: "error", message: "file not found" }, 404);
    }

    // Put /transcriptions — upload txt file under {jobid}.txt
    if (req.method === "PUT" && pathname.startsWith("/transcriptions")) {
      const form = await req.formData();
      const file = form.get("file") as File | null;
      const jobid = form.get("jobid") as string | null;

      if (!file || !jobid) {
        return json(
          { status: "error", message: "file and jobid required" },
          400
        );
      }

      const key = `transcriptions/${jobid}.txt`;
      console.log("PUT transcription", { jobid, key });
      await s3.send(
        new PutObjectCommand({
          Bucket: BUCKET,
          Key: key,
          Body: new Uint8Array(await file.arrayBuffer()),
          ContentType: "text/plain",
        })
      );

      return json({ status: "ok", jobid, key, message: "updated in place" });
    }

    // DELETE /transcriptions/:jobid — delete transcription file
    if (req.method === "DELETE" && pathname.startsWith("/transcriptions")) {
      let Key;
      Key = pathname.replace("/transcriptions/", "");

      console.log("attempt to delete: ", Key);
      try {
        await s3.send(new DeleteObjectCommand({ Bucket: BUCKET, Key }));

        return json({ status: "ok", message: "file deleted successfully" });
      } catch {
        return json({ status: "error", message: "file not found" }, 404);
      }
      // return json({ status: "error", message: "file not found" }, 404);
    }

    // GET /transcriptions/:jobid —
    const tMatch = pathname.match(/^\/transcriptions\/(.+)$/);
    if (req.method === "GET" && tMatch) {
      const jobid = tMatch[1];
      const Key = `transcriptions/${jobid}.txt`;

      try {
        const res = await s3.send(
          new GetObjectCommand({ Bucket: BUCKET, Key })
        );
        return new Response(res.Body as any, {
          headers: { "Content-Type": "text/plain" },
        });
      } catch {
        return json({ status: "error", message: "file not found" }, 404);
      }
    }

    return json({ status: "error", message: "not found" }, 404);
  },
});

console.log(`API running at http://localhost:${app.port}`);
