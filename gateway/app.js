import express from "express";
import { createProxyMiddleware } from "http-proxy-middleware";

const app = express();

/**
 * in-memory usage counter keyed by a coarse prefix or raw path
 * { "/auth": 10, "/api": 21, "/s3": 44, "/": 105, "/health": 3 }
 */
const usageStats = {};  // { "/auth": 10, "/api": 21, "/s3": 44, "/": 105 }

/**
 * increments an in-memory counter for the given prefix or path
 * this is process local, resets on restart
 * @param {string} prefix
 */
function trackUsage(prefix) {
  if (!usageStats[prefix]) usageStats[prefix] = 0;
  usageStats[prefix]++;
}

/**
 * cors with credentials and dynamic origin echo
 */
app.use((req, res, next) => {
  const origin = req.headers.origin || "*";

  res.header("Access-Control-Allow-Origin", origin);
  res.header("Access-Control-Allow-Credentials", "true");
  res.header("Access-Control-Allow-Methods", "GET,POST,PUT,DELETE,OPTIONS");
  res.header("Access-Control-Allow-Headers", "Content-Type,Authorization,Cookie");
  res.header("Vary", "Origin");

  if (req.method === "OPTIONS") {
    return res.sendStatus(204);
  }

  next();
});

/**
 * factory for http-proxy-middleware instances
 * for each proxied request it
 *  bumps the usage counter for the logical prefix
 *  rewrites the path if a rewrite function is provided
 *  forwards websocket upgrades
 *  sets the host header to match the target to appease certain backends
 * @param {string} prefix logical prefix
 * @param {string} target absolute target url
 * @param {(path:string, req?:import('http').IncomingMessage)=>string} rewrite
 * @returns {import('http-proxy-middleware').RequestHandler}
 */
function makeProxy(prefix, target, rewrite) {
  return createProxyMiddleware({
    target,
    changeOrigin: true,
    selfHandleResponse: false,
    ws: true,
    secure: true,
    onProxyReq: (proxyReq, req, res) => {
      trackUsage(prefix);
    },
    pathRewrite: rewrite,
    headers: {
      Host: new URL(target).host,
    }
  });
}

/**
 * this runs before specific prefix proxies
 * records the raw request path
 */
app.use((req, res, next)=>{
    // get request path
    trackUsage(req.path);
    next(); 
}
)

/**
 * auth service; strips /auth
 */
app.use(
  "/auth",
  makeProxy(
    "/auth",
    "http://auth:3000",
    (path) => path.replace(/^\/auth\/?/, "/")
  )
);


/**
 * transcription api service; forwards both http and ws traffic, strips /api
 */
app.use(
  "/api",
  makeProxy(
    "/api",
    "https://pataka.tail2feabe.ts.net",
    (path) => path.replace(/^\/api\/?/, "/")
  )
);

/**
 * s3 storage service, strips /s3
 */
app.use(
  "/s3",
  makeProxy(
    "/s3",
    "http://s3:6767",
    (path) => path.replace(/^\/s3\/?/, "/")
  )
);

/**
 * json endpoint to inspect usage counters
 */
app.get("/__usage", (req, res) => {
  res.json(usageStats);
});

/**
 * frontend fallback; proxies any remaining paths to the ui host with no rewrite
 */
app.use(
  "/",
  makeProxy(
    "/",
    "https://ytyz-transcriber.com",
    (path) => path // no rewrite
  )
);


app.listen(8082, () => {
  console.log("proxy running at http://localhost:8082");
});
