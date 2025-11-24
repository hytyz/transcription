import express from "express";
import path from "path";
const app = express();

/**
 * serves static assets from the project root and falls back to index.html for any route
 * useful for client-side routers that handle navigation on the browser
 */
app.use(express.static("./"));

app.get(/.*/, (req, res) => {
  res.sendFile(path.join(process.cwd(), "index.html"));
});

app.listen(9000);
