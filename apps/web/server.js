const http = require("node:http");

if (process.argv.includes("--health")) {
  process.exit(0);
}

const port = Number.parseInt(process.env.PORT || "3000", 10);
const apiBaseUrl = process.env.FOUNDER_API_BASE_URL || "http://api:8000";

const server = http.createServer((request, response) => {
  if (request.url === "/health") {
    response.writeHead(200, { "content-type": "application/json" });
    response.end(JSON.stringify({ status: "ok" }));
    return;
  }
  response.writeHead(200, { "content-type": "text/html; charset=utf-8" });
  response.end(`<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><title>Founder</title></head>
<body>
<main>
<h1>Founder Hosted Runtime</h1>
<p>API: ${apiBaseUrl}</p>
</main>
</body>
</html>`);
});

server.listen(port, "0.0.0.0");
