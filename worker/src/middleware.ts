import { createMiddleware } from "hono/factory";
import { getCookie, setCookie, deleteCookie } from "hono/cookie";
import { sign, verify } from "hono/jwt";
import type { Context } from "hono";
import type { AppEnv } from "./env";
import { logger } from "./logger";

const STATE_CHANGING = ["POST", "PUT", "DELETE", "PATCH"];

export const session = createMiddleware<AppEnv>(async (c, next) => {
  c.set("email", null);
  const header = c.req.header("authorization");
  const token = getCookie(c, "token") ?? (header?.startsWith("Bearer ") ? header.slice(7) : undefined);
  if (token) {
    try {
      const payload = await verify(token, c.env.JWT_SECRET, "HS256");
      if (typeof payload.email === "string") c.set("email", payload.email);
    } catch (err) {
      logger.debug("invalid session token", { error: (err as Error).message });
    }
  }
  await next();
});

export const csrf = createMiddleware<AppEnv>(async (c, next) => {
  if (STATE_CHANGING.includes(c.req.method) && c.req.header("x-requested-with") !== "XMLHttpRequest") {
    logger.warn("csrf validation failed", { method: c.req.method, path: c.req.path });
    return c.json({ error: "csrf validation failed: missing x-requested-with header" }, 403);
  }
  await next();
});

export const requireAuth = createMiddleware<AppEnv>(async (c, next) => {
  if (!c.get("email")) return c.json({ error: "not logged in" }, 401);
  await next();
});

export function rateLimit(binding: "AUTH_LIMITER") {
  return createMiddleware<AppEnv>(async (c, next) => {
    const key = c.req.header("cf-connecting-ip") ?? "local";
    const { success } = await c.env[binding].limit({ key });
    if (!success) {
      logger.warn("rate limited", { binding, path: c.req.path });
      return c.json({ error: "too many attempts, please try again later" }, 429);
    }
    await next();
  });
}

export async function startSession(c: Context<AppEnv>, email: string) {
  const expSeconds = parseInt(c.env.JWT_EXP_SECONDS, 10);
  const now = Math.floor(Date.now() / 1000);
  const token = await sign({ email, iat: now, exp: now + expSeconds }, c.env.JWT_SECRET, "HS256");
  setCookie(c, "token", token, {
    httpOnly: true,
    secure: true,
    sameSite: "Lax",
    maxAge: expSeconds,
    path: "/",
  });
}

export function endSession(c: Context<AppEnv>) {
  deleteCookie(c, "token", { path: "/", secure: true, httpOnly: true, sameSite: "Lax" });
}
