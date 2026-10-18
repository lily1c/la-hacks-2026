const http = require("node:http");

const port = Number(process.env.PORT || 8787);
let latest = null;

function send(res, status, body) {
  res.writeHead(status, {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
    ...(body ? { "Content-Type": "application/json" } : {}),
  });
  res.end(body ? JSON.stringify(body) : undefined);
}

const server = http.createServer((req, res) => {
  if (req.method === "OPTIONS") return send(res, 204);
  if (req.url !== "/latest") return send(res, 404, { error: "Not found" });
  if (req.method === "GET") return latest ? send(res, 200, latest) : send(res, 204);
  if (req.method !== "POST") return send(res, 405, { error: "Method not allowed" });

  let raw = "";
  req.on("data", (chunk) => { raw += chunk; });
  req.on("end", () => {
    let alert;
    try {
      alert = JSON.parse(raw);
    } catch {
      return send(res, 400, { error: "Body must be valid JSON" });
    }
    if (!alert || typeof alert.headline !== "string" || !alert.headline.trim()) {
      return send(res, 422, { error: "headline is required" });
    }
    const instructions = alert.instructions ?? [];
    if (alert.headline.length > 40 || !Array.isArray(instructions) || instructions.length > 5 ||
        instructions.some((line) => typeof line !== "string" || line.length > 40)) {
      return send(res, 422, { error: "headline and instructions exceed display limits" });
    }
    latest = {
      id: String(alert.id ?? Date.now()),
      timestamp: alert.timestamp ?? new Date().toISOString(),
      priority: ["critical", "warning", "info"].includes(alert.priority) ? alert.priority : "info",
      headline: alert.headline,
      instructions,
    };
    return send(res, 200, latest);
  });
});

server.listen(port, "0.0.0.0", () => {
  console.log(`FireSight mock API listening at http://localhost:${port}/latest`);
});
