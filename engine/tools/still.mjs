#!/usr/bin/env node
/**
 * still.mjs —— 从任意 HTML 镜头页取一张/几张静帧 PNG（开发与复测用）。
 *
 *   node tools/still.mjs shot.html --time 2.4 --out a.png
 *   node tools/still.mjs shot.html --times 0,1.5,3 --outdir stills/
 *
 * 与 render_html.mjs 共用同一套浏览器参数，保证“静帧看到的就是成片里的那一帧”。
 */
import { servePage } from "../scripts/page_server.mjs";
import fs from "node:fs";
import path from "node:path";
import puppeteer from "puppeteer";

const argv = process.argv;
const arg = (n, d) => (argv.indexOf(`--${n}`) > 0 ? argv[argv.indexOf(`--${n}`) + 1] : d);
const htmlPath = argv[2];
if (!htmlPath || !fs.existsSync(htmlPath)) {
  console.error("用法: node still.mjs shot.html --time 2.4 --out a.png  |  --times 0,1,2 --outdir dir");
  process.exit(1);
}

const times = (arg("times", "") || "").split(",").filter(Boolean).map(Number);
const single = arg("time", "");
if (single !== "") times.push(Number(single));
if (!times.length) times.push(Number(arg("t", "0")) || 0);
const outdir = arg("outdir", "");
const out = arg("out", "still.png");
const [W, H] = (arg("size", "1920x1080")).split("x").map(Number);
async function main() {
  const server = await servePage(htmlPath);
  const port = server.address().port;
  const launchOpts = {
    headless: "new",
    args: ["--use-gl=angle", "--use-angle=d3d11", "--enable-gpu", "--ignore-gpu-blocklist",
      "--enable-gpu-rasterization",  
      `--window-size=${W},${H}`, "--disable-dev-shm-usage"],
  };
  const envExe = process.env.PUPPETEER_EXECUTABLE_PATH || process.env.CHROME_PATH;
  if (envExe) launchOpts.executablePath = envExe;
  const browser = await puppeteer.launch(launchOpts);
  const page = await browser.newPage();
  page.on("pageerror", (e) => console.log("[pageerror]", e.message));
  page.on("console", (m) => { if (m.type() === "error") console.log("[page]", m.text()); });
  await page.setViewport({ width: W, height: H, deviceScaleFactor: 1 });
  await page.goto(`http://127.0.0.1:${port}/${encodeURIComponent(path.basename(htmlPath))}`, { waitUntil: "load" });
  await page.evaluate(() => {
    if (typeof window.renderFrame === "function") return;
    if (window.film && typeof window.film.frame === "function") window.renderFrame = (t) => window.film.frame(t);
    else if (typeof window.__frame === "function") window.renderFrame = (t) => window.__frame(t);
  });
  await page.waitForFunction("typeof window.renderFrame === 'function'", { timeout: 180000 });
  await page.evaluate(async () => { if (window.film?.ready) await window.film.ready; });
  await page.evaluate(() => document.fonts.ready.then(() => true));
  for (const t of times) {
    await page.evaluate((tt) => window.renderFrame(tt), t);
    const dest = outdir ? path.join(outdir, `t${t.toFixed(2).replace(".", "_")}.png`) : out;
    fs.mkdirSync(path.dirname(path.resolve(dest)), { recursive: true });
    await page.screenshot({ path: dest, clip: { x: 0, y: 0, width: W, height: H } });
    console.log(`${dest}  t=${t}`);
  }
  await browser.close();
  server.close();
}
main().catch((e) => { console.error(e); process.exit(1); });
