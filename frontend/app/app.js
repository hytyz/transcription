import express from "express";
import path from "path";
const app = express();
// const path = path()

app.use(express.static("./"));

app.get(/.*/, (req, res) => {
  res.sendFile(path.join(process.cwd(), "index.html"));
});


app.listen(9000);
