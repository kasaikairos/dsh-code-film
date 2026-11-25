#!/usr/bin/env node
/**
 * layout_audit.mjs —— 版式审计：检查文字/卡片是否出画、越安全边距、互相重叠。
 *
 *   node scripts/layout_audit.mjs <page.html> [--safe 0.06] [--json out.json]
 *
 * 判据（与 references/判断.md 的工艺红线一致）：
 *   1) 所有可见文字/卡片落在画布内
 *   2) 距四边留白 ≥ safe（默认 6%）
 *   3) 文字与卡片之间不重叠（卡片作为底板不算冲突）
 */
import { servePage } from "./page_server.mjs";
import fs from "node:fs";
import path from "node:path";
import puppeteer from "puppeteer";

const argv = process.argv;
const arg = (n, d) => (argv.indexOf(`--${n}`) > 0 ? argv[argv.indexOf(`--${n}`) + 1] : d);
const htmlPath = argv[2];
if (!htmlPath || !fs.existsSync(htmlPath)) {
  console.error("用法: node layout_audit.mjs page.html [--safe 0.06] [--json out.json]");
  process.exit(2);
}
const SAFE = parseFloat(arg("safe", "0.06"));
const OUT = arg("json", "");

const server = await servePage(htmlPath);
const port = server.address().port;

const browser = await puppeteer.launch({
  headless: "new",
  args: ["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader"],
});
const page = await browser.newPage();
const errs = [];
page.on("pageerror", (e) => errs.push(String(e.message)));
await page.setViewport({ width: 1920, height: 1080, deviceScaleFactor: 1 });
await page.goto(`http://127.0.0.1:${port}/${encodeURIComponent(path.basename(htmlPath))}`, { waitUntil: "load" });
await page.waitForFunction("typeof window.renderFrame === 'function'", { timeout: 120000 });
await page.evaluate(() => window.renderFrame(1.0));

const info = await page.evaluate(() => {
  const sel = [".t", ".s", ".i", ".card"];
  const out = [];
  for (const s of sel) {
    document.querySelectorAll(s).forEach((el, k) => {
      const r = el.getBoundingClientRect();
      if (r.width < 1 || r.height < 1) return;
      out.push({ sel: s, k, x: r.x, y: r.y, w: r.width, h: r.height,
                 text: (el.textContent || "").trim().slice(0, 30) });
    });
  }
  return { W: window.innerWidth, H: window.innerHeight, items: out };
});
await browser.close();
server.close();

const { W, H, items } = info;
const issues = [];
const sx = W * SAFE - 1.5, sy = H * SAFE - 1.5;   // 1.5px 容差（字体度量取整）
for (const it of items) {
  if (it.x < -0.5 || it.y < -0.5 || it.x + it.w > W + 0.5 || it.y + it.h > H + 0.5)
    issues.push(`出画：${it.sel}「${it.text}」(${Math.round(it.x)},${Math.round(it.y)},${Math.round(it.w)}x${Math.round(it.h)})`);
  if (it.sel !== ".card" && (it.x < sx || it.y < sy || it.x + it.w > W - (W * SAFE - 1.5) || it.y + it.h > H - (H * SAFE - 1.5)))
    issues.push(`越安全边距(6%)：${it.sel}「${it.text}」左${Math.round(it.x)} 上${Math.round(it.y)} 右${Math.round(W - it.x - it.w)} 下${Math.round(H - it.y - it.h)}`);
}
const texts = items.filter((i) => i.sel !== ".card");
for (let i = 0; i < texts.length; i++) {
  for (let j = i + 1; j < texts.length; j++) {
    const a = texts[i], b = texts[j];
    const ox = Math.max(0, Math.min(a.x + a.w, b.x + b.w) - Math.max(a.x, b.x));
    const oy = Math.max(0, Math.min(a.y + a.h, b.y + b.h) - Math.max(a.y, b.y));
    if (ox > 2 && oy > 2) issues.push(`文字重叠：${a.sel}「${a.text}」与 ${b.sel}「${b.text}」`);
  }
}
const report = { page: path.basename(htmlPath), canvas: [W, H], safe_margin: SAFE,
                 items: items.length, issues, pageerrors: errs };
const txt = JSON.stringify(report, null, 1);
if (OUT) fs.writeFileSync(OUT, txt);
console.log(txt);
process.exit(issues.length || errs.length ? 1 : 0);
