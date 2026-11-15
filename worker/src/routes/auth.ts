import { Hono } from "hono";
import type { AppEnv } from "../env";
import { logger } from "../logger";
import { genSalt, hashPassword, verifyPassword } from "../password";
import { rateLimit, requireAuth, startSession, endSession } from "../middleware";

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

type Credentials = { email?: unknown; password?: unknown };

function readCredentials(body: Credentials): { email: string; password: string } | { error: string } {
  const { email, password } = body;
  if (typeof email !== "string" || typeof password !== "string" || !email || !password) {
    return { error: "email and password required" };
  }
  if (email.length > 254 || !EMAIL_RE.test(email)) return { error: "invalid email format" };
  if (password.length < 8) return { error: "password must be at least 8 characters" };
  if (password.length > 1024) return { error: "password is too long" };
  return { email, password };
}

const auth = new Hono<AppEnv>();

auth.post("/create", rateLimit("AUTH_LIMITER"), async (c) => {
  const creds = readCredentials(await c.req.json<Credentials>().catch(() => ({})));
  if ("error" in creds) {
    logger.warn("registration failed", { reason: creds.error });
    return c.json({ error: creds.error }, 400);
  }

  const salt = genSalt();
  const hash = await hashPassword(creds.password, salt);
  const result = await c.env.DB.prepare(
    "INSERT INTO users(email, password_hash, salt, api_usage) VALUES(?, ?, ?, 0) ON CONFLICT(email) DO NOTHING",
  )
    .bind(creds.email, hash, salt)
    .run();

  if (result.meta.changes === 0) {
    logger.warn("registration failed: user exists", { email: creds.email });
    return c.json({ error: "user already exists" }, 409);
  }

  await startSession(c, creds.email);
  logger.info("user registered", { email: creds.email });
  return c.json({ ok: true });
});

auth.post("/login", rateLimit("AUTH_LIMITER"), async (c) => {
  if (!c.req.header("content-type")?.includes("application/json")) {
    return c.json({ error: "content-type must be application/json" }, 415);
  }
  const body = await c.req.json<Credentials>().catch(() => ({}) as Credentials);
  if (typeof body.email !== "string" || typeof body.password !== "string") {
    return c.json({ error: "email and password required" }, 400);
  }
  const email = body.email.trim();

  const row = await c.env.DB.prepare("SELECT password_hash, salt FROM users WHERE email = ?")
    .bind(email)
    .first<{ password_hash: string; salt: string }>();

  if (!row || !(await verifyPassword(body.password, row.salt, row.password_hash))) {
    logger.warn("login failed", { email });
    return c.json({ error: "invalid credentials" }, 401);
  }

  await startSession(c, email);
  logger.info("user logged in", { email });
  return c.json({ ok: true });
});

auth.post("/logout", (c) => {
  endSession(c);
  return c.json({ ok: true });
});

auth.get("/me", requireAuth, (c) => c.json({ payload: { email: c.get("email") } }));

auth.get("/myusage", requireAuth, async (c) => {
  const email = c.get("email")!;
  const row = await c.env.DB.prepare("SELECT api_usage FROM users WHERE email = ?")
    .bind(email)
    .first<{ api_usage: number }>();
  if (!row) return c.json({ error: "user not found" }, 404);
  return c.json({ email, usage: row.api_usage });
});

auth.get("/usage", requireAuth, async (c) => {
  if (!c.env.ADMIN_EMAIL || c.get("email") !== c.env.ADMIN_EMAIL) {
    return c.json({ error: "forbidden" }, 403);
  }
  const { results } = await c.env.DB.prepare("SELECT email, api_usage FROM users ORDER BY email").all();
  return c.json({ users: results });
});

export default auth;
