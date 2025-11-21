import express from "express";
import { createProxyMiddleware } from "http-proxy-middleware";

const app = express();

const usageStats = {};  // { "/auth": 10, "/api": 21, "/s3": 44, "/": 105 }

function trackUsage(prefix) {
  if (!usageStats[prefix]) usageStats[prefix] = 0;
  usageStats[prefix]++;
}

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

app.use((req, res, next)=>{
    // get request path
    trackUsage(req.path);
    next();
}
)

app.use(
  "/auth",
  makeProxy(
    "/auth",
    "https://polina-auth.fly.dev",
    (path) => path.replace(/^\/auth\/?/, "/")
  )
);

app.use(
  "/api",
  makeProxy(
    "/api",
    "https://pataka.tail2feabe.ts.net",
    (path) => path.replace(/^\/api\/?/, "/")
  )
);

app.use(
  "/s3",
  makeProxy(
    "/s3",
    "https://s3-aged-water-5651.fly.dev",
    (path) => path.replace(/^\/s3\/?/, "/")
  )
);

app.get("/__usage", (req, res) => {
  res.json(usageStats);
});

app.use(
  "/",
  makeProxy(
    "/",
    "https://taupekhana.tail2feabe.ts.net",
    (path) => path // no rewrite
  )
);


app.listen(8080, () => {
  console.log("Proxy running at http://localhost:8080");
});
