import { Hono } from "hono";
import { createMiddleware } from "hono/factory";
import { routePath } from "hono/route";
import type { AppEnv } from "../env";
import { logger } from "../logger";
import { session, requireAuth } from "../middleware";

export const trackUsage = createMiddleware<AppEnv>(async (c, next) => {
  await next();
  const route = routePath(c, -1);
  if (!route || route.startsWith("/api/worker") || route === "*" || route.endsWith("/*")) return;
  c.executionCtx.waitUntil(
    c.env.DB.prepare("INSERT INTO route_usage(route, count) VALUES(?, 1) ON CONFLICT(route) DO UPDATE SET count = count + 1")
      .bind(`${c.req.method} ${route}`)
      .run()
      .catch((err: Error) => logger.error("usage tracking failed", { route, error: err.message })),
  );
});

const usage = new Hono<AppEnv>();

usage.get("/", session, requireAuth, async (c) => {
  if (!c.env.ADMIN_EMAIL || c.get("email") !== c.env.ADMIN_EMAIL) {
    return c.json({ error: "forbidden" }, 403);
  }
  const { results } = await c.env.DB.prepare("SELECT route, count FROM route_usage ORDER BY count DESC").all<{
    route: string;
    count: number;
  }>();
  return c.json(Object.fromEntries(results.map((r) => [r.route, r.count])));
});

export default usage;
