import { Hono } from "hono";
import type { AppEnv } from "./env";
import { logger } from "./logger";
import { session, csrf } from "./middleware";
import auth from "./routes/auth";
import { transcriptions, files } from "./routes/transcriptions";

const app = new Hono<AppEnv>({ strict: false });

app.use("*", async (c, next) => {
  const start = Date.now();
  await next();
  logger.info("request", {
    method: c.req.method,
    path: c.req.path,
    status: c.res.status,
    durationMs: Date.now() - start,
  });
});

app.use("/auth/*", session, csrf);
app.use("/s3/*", session, csrf);

app.route("/auth/transcriptions", transcriptions);
app.route("/auth", auth);
app.route("/s3", files);

app.get("/api/health", (c) => c.json({ ok: true }));

app.notFound((c) => c.json({ error: "not found" }, 404));

app.onError((err, c) => {
  logger.error("unhandled error", { path: c.req.path, error: err.message });
  return c.json({ error: "internal error" }, 500);
});

export default app;
