import { createHash } from "node:crypto";
import http from "node:http";
import fs from "node:fs";
import path from "node:path";

const types = {
  ".html":"text/html; charset=utf-8", ".js":"text/javascript", ".mjs":"text/javascript",
  ".json":"application/json", ".css":"text/css", ".svg":"image/svg+xml", ".png":"image/png", ".jpg":"image/jpeg",
  ".woff2":"font/woff2", ".ttf":"font/ttf", ".otf":"font/otf", ".glsl":"text/plain",
  ".mp3":"audio/mpeg", ".wav":"audio/wav"
};

const sourceTypes = new Set([".html", ".js", ".mjs", ".json", ".css", ".woff2", ".ttf", ".otf", ".glsl", ".vert", ".frag", ".wgsl"]);
const sourcePolicy = [
  "default-src 'none'", "script-src 'self' 'unsafe-inline'", "style-src 'self' 'unsafe-inline'",
  "font-src 'self'", "connect-src 'self'", "img-src 'none'", "media-src 'none'",
  "frame-src 'none'", "base-uri 'none'"
].join("; ");

export async function servePage(pagePath, record, {sourceOnly = false} = {}) {
  const root = fs.realpathSync(path.dirname(path.resolve(pagePath)));
  const blocked = new Set();
  const server = http.createServer((req, res) => {
    if (sourceOnly) res.setHeader("Content-Security-Policy", sourcePolicy);
    if (req.headers.host !== `127.0.0.1:${server.address().port}`) {
      res.writeHead(403).end();
      return;
    }
    let requested;
    try {
      const url = decodeURIComponent(req.url.split("?")[0]);
      requested = path.join(root, url === "/" ? path.basename(pagePath) : url);
      const file = fs.realpathSync(requested);
      const relative = path.relative(root, file);
      if (relative === ".." || relative.startsWith(".." + path.sep) ||
          path.isAbsolute(relative) || !fs.statSync(file).isFile()) {
        res.writeHead(404).end();
        return;
      }
      const ext = path.extname(file).toLowerCase();
      if (sourceOnly && !sourceTypes.has(ext)) {
        if (relative !== "favicon.ico") blocked.add(relative);
        res.writeHead(403).end();
        return;
      }
      res.writeHead(200, { "Content-Type": types[ext] || "application/octet-stream" });
      if (record) {
        const bytes = fs.readFileSync(file);
        record(path.relative(root, requested), createHash("sha256").update(bytes).digest("hex"));
        res.end(bytes);
        return;
      }
      fs.createReadStream(file).on("error", () => res.destroy()).pipe(res);
    } catch {
      if (record && requested) record(path.relative(root, requested), null);
      res.writeHead(404).end();
    }
  });
  await new Promise((resolve, reject) => server.once("error", reject).listen(0, "127.0.0.1", resolve));
  server.blockedSources = blocked;
  return server;
}
