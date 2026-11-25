#!/usr/bin/env node
/**
 * render_html.mjs —— 把**一个 HTML 文件**渲成视频（单文件电影路径）。
 *
 * 学自 abstract-algebra-promo：整部片是一个 HTML（Canvas/WebGL + 内联数据），
 * 页面里只暴露一个纯函数 `window.renderFrame(t)`；这里负责逐帧截图 + 编码。
 *
 *   node scripts/render_html.mjs film.html --out out/film.mp4 --frames 300 --preset uhd
 *
 * 约定（HTML 侧只需满足这两条）：
 *   1) `window.renderFrame(t)`  —— t 为秒，返回后画面即为该时刻
 *   2) `window.FILM = { width, height, fps, duration }`（可选，缺省用 --preset/--frames）
 */
import { servePage } from "./page_server.mjs";
import fs from "node:fs";
import path from "node:path";
import { spawn } from "node:child_process";
import puppeteer from "puppeteer";

const argv = process.argv;
const arg = (n, d) => (argv.indexOf(`--${n}`) > 0 ? argv[argv.indexOf(`--${n}`) + 1] : d);
const htmlPath = argv[2];
if (!htmlPath || !fs.existsSync(htmlPath)) {
  console.error("用法: node render_html.mjs film.html --out out/film.mp4 [--frames N] [--preset uhd]");
  process.exit(1);
}

const PRESETS = { draft: [1280, 720], hd: [1920, 1080], qhd: [2560, 1440], uhd: [3840, 2160] };
const preset = arg("preset", "uhd");
const DPR = parseFloat(arg("dpr", "1"));       // openfilm 的 4K：页面仍是 1920，靠 devicePixelRatio=2 输出真 4K
const VIEWPORT = arg("viewport", "");          // 覆盖逻辑视口，如 1920x1080
let [W, H] = PRESETS[preset] || PRESETS.uhd;
if (VIEWPORT) {
  const [vw, vh] = VIEWPORT.split("x").map(Number);
  if (vw > 0 && vh > 0) { W = vw; H = vh; }
}
const GPU_ARG = arg("gpu", null);   // auto|on|off
// 默认串行：单 GPU 上多页面会互相抢显存/截图，实测更慢；只在 CPU-bound 页面用
const JOBS = Math.max(1, Math.min(8, parseInt(arg("jobs", "1"), 10) || 1));
const QUIET = argv.includes("--quiet") || process.env.RENDER_QUIET === "1";
const LOGF = arg("log", "") || "";
const say = (...a) => { const line = a.join(" "); if (LOGF) { try { fs.appendFileSync(LOGF, line + "\n"); } catch (e) {} } if (!QUIET) console.log(line); };
const shownDiagnostics=new Set();
let suppressedDiagnostics=0;
function diagnostic(kind,value) {
  const message=`[${kind}] ${String(value)}`;
  say(message);
  if (!QUIET) return;
  const excerpt=message.replace(/\s+/g," ").slice(0,240);
  if (shownDiagnostics.size<4 && !shownDiagnostics.has(excerpt)) {
    shownDiagnostics.add(excerpt);
    console.error(excerpt);
  } else {
    suppressedDiagnostics++;
  }
}
function attachDiagnostics(page) {
  page.on("pageerror",error=>diagnostic("pageerror",error.message));
  page.on("console",message=>{
    if (message.type()==="error") diagnostic("page",message.text());
  });
}
const START = Number(arg("start", "0"));
const END_ARG = Number(arg("end", "0"));
// 截图格式：JPEG 比 PNG 快很多（最终还要编码成 h264，画质损失可忽略）
const shot=(arg("shot",process.env.SHOT_FMT || "jpeg") || "jpeg").toLowerCase();
if (!["jpeg","png","png-fast"].includes(shot)) {
  console.error("--shot must be jpeg, png or png-fast");
  process.exit(2);
}
const fastPNG=shot==="png-fast";
const SHOT_FMT=fastPNG ? "png" : shot;
const SHOT_EXT = SHOT_FMT === "png" ? ".png" : ".jpg";
const OUT = path.resolve(arg("out", "out/film.mp4"));
const FRAMES = Number(arg("frames", "300"));
const FPS = Number(arg("fps", "30"));
const BLUR = Number(arg("blur", "1"));  // Samples per output frame.
const CRF = parseInt(arg("crf", "14"), 10);
const CODEC = arg("codec", "x264");            // x264（锐利、通用）| x265（更小）
const SCALE = arg("scale", "");                // 例如 "1920:1080"：超采样后下采样
const PRESET = arg("encpreset", "slow");

const stills = arg("stills", "");
const requestedStills = argv.includes("--stills");
const variantStills = arg("variant-stills","");
const variantNames = variantStills ? JSON.parse(fs.readFileSync(variantStills,"utf8")) : null;
const stillTimes = stills.split(",").map(t=>t.trim()==="" ? NaN : Number(t));
if (requestedStills && (!stills || stillTimes.some(t=>!Number.isFinite(t)||t<0) ||
    stillTimes.length>12 || (!variantNames && new Set(stillTimes).size!==stillTimes.length))) {
  console.error("--stills expects 1–12 distinct nonnegative times in seconds");
  process.exit(2);
}
if (variantNames && (!requestedStills || !Array.isArray(variantNames) ||
    variantNames.length!==stillTimes.length ||
    variantNames.some(id=>typeof id!=="string" || !/^[A-Za-z0-9_-]{1,32}$/.test(id)))) {
  console.error("--variant-stills must supply one identifier per still");
  process.exit(2);
}
const depsOut = arg("deps-out", "");
const metricsPath = arg("metrics", "");
const rangesPath = arg("ranges", "");
const holdsPath = arg("holds", "");
if (![START,END_ARG,FRAMES,FPS,BLUR].every(Number.isSafeInteger) ||
    Math.min(START,END_ARG)<0 || Math.min(FRAMES,FPS,BLUR)<=0 ||
    (END_ARG!==0 && END_ARG<=START)) {
  console.error("invalid output frame range, fps or subframe count");
  process.exit(2);
}
let ranges;
if (rangesPath) {
  if (requestedStills || JOBS!==1 ||
      ["--start","--end","--frames"].some(flag=>argv.includes(flag))) {
    console.error("--ranges uses one browser and replaces --start, --end and --frames");
    process.exit(2);
  }
  ranges=JSON.parse(fs.readFileSync(rangesPath,"utf8").replace(/^\uFEFF/,""));
  if (!Array.isArray(ranges) || !ranges.length || ranges.length>24 ||
      ranges.some(row=>!row || !Number.isSafeInteger(row.start) || !Number.isSafeInteger(row.frames) ||
        row.start<0 || row.frames<=0 || !Number.isSafeInteger(row.start+row.frames))) {
    console.error("--ranges expects 1–24 {start,frames} entries in output frames");
    process.exit(2);
  }
} else {
  ranges=[{start:START,frames:END_ARG ? END_ARG-START : FRAMES}];
}
const totalFrames=ranges.reduce((sum,row)=>sum+row.frames,0);
if (!ranges.every(row=>Number.isSafeInteger((row.start+row.frames)*BLUR)) ||
    !Number.isSafeInteger(totalFrames*BLUR)) process.exit(2);
const holds=holdsPath ? JSON.parse(fs.readFileSync(holdsPath,"utf8").replace(/^\uFEFF/,"")) : [];
if (holdsPath && (JOBS!==1 || requestedStills || !Array.isArray(holds) || holds.length>120 ||
    holds.some((row,i)=>!row || !Number.isSafeInteger(row.start) || !Number.isSafeInteger(row.frames) ||
      row.start<0 || row.frames<4 || !Number.isSafeInteger((row.start+row.frames)*BLUR) ||
      (i>0 && holds[i-1].start+holds[i-1].frames>row.start)))) {
  console.error("--holds needs one page and ordered nonoverlapping {start,frames} ranges of at least four frames");
  process.exit(2);
}

const dependencies = new Map();
let reusable = true;
function record(name, digest) {
  if (dependencies.has(name) && dependencies.get(name) !== digest) reusable = false;
  dependencies.set(name, digest);
}
async function main() {
  const started=performance.now();
  fs.mkdirSync(path.dirname(OUT), {recursive:true});
  const fdir = fs.mkdtempSync(path.join(path.dirname(OUT), ".film-frames-"));
  try {
  const server = await servePage(htmlPath, depsOut ? record : null);
  const port = server.address().port;
  // GPU 选择：auto=先用显卡，检测到软件渲染会提示；on=强制显卡；off=强制软件
  const GPU_MODE = String(process.env.RENDER_GPU || GPU_ARG || "auto").toLowerCase();
  const gpuArgs = [
    "--use-gl=angle", "--use-angle=d3d11", "--enable-gpu", "--ignore-gpu-blocklist",
    "--enable-gpu-rasterization", 
     "--disable-dev-shm-usage",
    `--window-size=${W},${H}`, "--autoplay-policy=no-user-gesture-required",
  ];
  const swArgs = [
    "--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader",
     "--disable-dev-shm-usage",
    `--window-size=${W},${H}`, "--autoplay-policy=no-user-gesture-required",
  ];
  const launchArgs = (GPU_MODE === "off") ? swArgs : gpuArgs;
  // 跨平台：浏览器路径可用 PUPPETEER_EXECUTABLE_PATH 指定；找不到就退回 puppeteer 自带
  const launchOpts = {
    headless: "new",
    args: launchArgs,
  };
  const envExe = process.env.PUPPETEER_EXECUTABLE_PATH || process.env.CHROME_PATH;
  if (envExe) launchOpts.executablePath = envExe;
  let browser;
  try {
    browser = await puppeteer.launch(launchOpts);
  } catch (e) {
    console.error("[render] 无法启动浏览器：", e.message);
    console.error("  解决：设置环境变量 PUPPETEER_EXECUTABLE_PATH 指向 Chrome/Chromium，");
    console.error("        或在本目录执行 npx puppeteer browsers install chrome");
    process.exit(2);
  }
  let page = await browser.newPage();
  attachDiagnostics(page);
  await page.setViewport({ width: W, height: H, deviceScaleFactor: DPR });
  // 检测 WebGL 实际用的渲染器（GPU 还是 SwiftShader）
  async function glRenderer(pg) {
    try {
      return await pg.evaluate(() => {
        const c = document.createElement("canvas");
        const gl = c.getContext("webgl2") || c.getContext("webgl");
        if (!gl) return "none";
        const ext = gl.getExtension("WEBGL_debug_renderer_info");
        return ext ? gl.getParameter(ext.UNMASKED_RENDERER_WEBGL) : "unknown";
      });
    } catch (e) { return "unknown"; }
  }
  let renderer = await glRenderer(page);
  const isSoft = /swiftshader|software|llvmpipe|none|unknown/i.test(String(renderer));
  say(`[gpu] WebGL 渲染器：${renderer}`);
  if (GPU_MODE === "auto" && isSoft) {
    console.log("[gpu] 没有可用显卡，回退软件渲染（CPU），速度会慢 2 倍左右");
    await page.close();
    await browser.close();
    launchOpts.args = swArgs;
    browser = await puppeteer.launch(launchOpts);
    page = await browser.newPage();
    attachDiagnostics(page);
    await page.setViewport({ width: W, height: H, deviceScaleFactor: DPR });
    renderer = await glRenderer(page);
    say(`[gpu] 回退后渲染器：${renderer}`);
  } else if (GPU_MODE === "off") {
    console.log("[gpu] 已按要求强制软件渲染（CPU）");
  }
  async function prepare(pg) {
  if (depsOut) pg.on("request", req => {
    const u = new URL(req.url());
    if (!["data:", "blob:", "about:"].includes(u.protocol) && u.origin !== `http://127.0.0.1:${port}`) reusable = false;
  });
  await pg.goto(`http://127.0.0.1:${port}/${encodeURIComponent(path.basename(htmlPath))}${argv.includes("--timeline") ? "?render=1" : ""}`, { waitUntil: "load" });
  if (argv.includes("--timeline")) {
    await pg.waitForFunction(() => window.__FILM_ERROR__ || window.__RENDER__?.setTime ||
      window.__FILM__?.renderAt || window.renderFrame, {timeout:120000});
    await pg.evaluate(() => {
      if (window.__FILM_ERROR__ || window.__RENDER__?.missing?.length)
        throw new Error(String(window.__FILM_ERROR__ || window.__RENDER__.missing));
      window.renderFrame ??= t => window.__RENDER__?.setTime ? window.__RENDER__.setTime(t) : window.__FILM__.renderAt(t);
    });
    if (argv.includes("--canvas-only")) await pg.evaluate(() => {
      const canvases = document.querySelectorAll("canvas");
      if (canvases.length !== 1) throw new Error("canvas-only requires exactly one canvas");
      window.filmCanvasOnly = true;
      window.filmCanvas = canvases[0];
    });
  }
  // 兼容：自家页面用 renderFrame(t)；openfilm 用 window.film.frame(t)；ai-history 用 window.__frame(t)
  await pg.evaluate(() => {
    if (typeof window.renderFrame === 'function') return;
    if (window.film && typeof window.film.frame === 'function') {
      window.renderFrame = (t) => window.film.frame(t);
    } else if (typeof window.__frame === 'function') {
      window.renderFrame = (t) => window.__frame(t);
    } else if (window.film && typeof window.film.render === 'function') {
      window.renderFrame = (t) => window.film.render(t);
    }
  });
  await pg.waitForFunction(() => window.__FILM_ERROR__ || typeof window.renderFrame === "function",
                           { timeout: 180000 });
  const error = await pg.evaluate(() => window.__FILM_ERROR__);
  if (error) throw new Error(error);
  // openfilm 的 section 页需要 ready（预编译 shader）
  await pg.evaluate(async () => { if (window.film && window.film.ready) await window.film.ready; });
    await pg.evaluate(() => document.fonts.ready.then(() => true));
  }
  if (requestedStills) {
    try {
      await prepare(page);
      fs.mkdirSync(OUT,{recursive:true});
      for (const [index,time] of stillTimes.entries()) {
        await page.evaluate(async ([t,id]) => {
          if (id!==null) {
            if (typeof window.setReviewVariant!=="function") throw new Error("missing setReviewVariant(id)");
            await window.setReviewVariant(id);
          }
          await window.renderFrame(t);
        },[time,variantNames?.[index] ?? null]);
        const name = `frame-${String(index+1).padStart(2,"0")}.png`;
        await page.screenshot({path:path.join(OUT,name),type:"png",clip:{x:0,y:0,width:W,height:H}});
      }
      fs.writeFileSync(path.join(OUT,"stills.json"), JSON.stringify({
        seconds:stillTimes,width:Math.round(W*DPR),height:Math.round(H*DPR),renderer
      },null,2));
      console.log(`${stillTimes.length} native stills | ${Math.round(W*DPR)}x${Math.round(H*DPR)} | ${OUT}`);
    } finally {
      try { await browser.close(); } finally { server.close(); }
    }
    return;
  }
  await prepare(page);
  const SUB=BLUR;
  const TOTAL=totalFrames*SUB;
  const firstSample=START*SUB;
  const finalSample=firstSample+TOTAL;
  const output=path.join(fdir,"complete"+(path.extname(OUT)||".mp4"));
  say(`[html] ${path.basename(htmlPath)}  ${W}x${H} @DPR${DPR} -> ${Math.round(W*DPR)}x${Math.round(H*DPR)}  ${totalFrames} 帧 @${FPS}fps`
              + (SUB > 1 ? `  ×${SUB} 子帧（运动模糊）` : ""));
  const t0 = Date.now();
  // ── 并行：把帧分给 N 个 page ──
  async function setupPage(br) {
    const pg = await br.newPage();
    attachDiagnostics(pg);
    await pg.setViewport({ width: W, height: H, deviceScaleFactor: DPR });
    await prepare(pg);
    return pg;
  }
  if (JOBS > 1) {
    const pages = [page];
    for (let k = 1; k < JOBS; k++) pages.push(await setupPage(browser));
    say(`[jobs] 并行 ${pages.length} 个页面渲 ${TOTAL} 帧`);
    let done = 0;
    await Promise.all(pages.map(async (pg, k) => {
      for (let i = firstSample + k; i < finalSample; i += JOBS) {
        await pg.evaluate((t) => window.renderFrame(t), i / (FPS * SUB));
        await pg.screenshot({
          path: path.join(fdir, String(i).padStart(5, "0") + SHOT_EXT),
          type: SHOT_FMT === "png" ? "png" : "jpeg",
          quality: SHOT_FMT === "png" ? undefined : 94,
          optimizeForSpeed:fastPNG,
          clip: { x: 0, y: 0, width: W, height: H },
        });
        done++;
        if (done % Math.max(1, Math.floor(TOTAL / 10)) === 0 || done === TOTAL) {
          const el = (Date.now() - t0) / 1000;
          say(`  ${done}/${TOTAL}  ${(el / done).toFixed(2)}s/帧  剩余 ~${((el / done) * (TOTAL - done)).toFixed(0)}s`);
        }
      }
    }));
    await browser.close();
    server.close();
    await finished(encoder({SUB,FPS,fdir,firstSample,output}, false));
    fs.renameSync(output,OUT);
    return;
  }

  const direct = await page.evaluate(([w,h]) => window.filmCanvasOnly === true && window.filmCanvas instanceof HTMLCanvasElement &&
    window.filmCanvas.width === w && window.filmCanvas.height === h,
    [Math.round(W*DPR),Math.round(H*DPR)]);
  const ready=performance.now();
  const proc = encoder({SUB,FPS,fdir,firstSample,output}, true);
  const done = finished(proc);
  done.catch(() => {});  // observed below, including early encoder exit
  proc.stdin?.on("error", () => {});
  const push=bytes=>new Promise((ok,fail)=>proc.stdin.write(bytes,err=>err ? fail(err) : ok()));
  const timings=[];
  let count=0;
  let reused=0,verifiedHolds=0,rejectedHolds=0;
  const inspected=new Map();
  let activeHold,still;
  try {
    for (const {start,frames} of ranges) {
      const begin=performance.now();
      let sceneMs=0,captureMs=0,pipeMs=0;
      const end=(start+frames)*SUB;
      async function capture(sample) {
        const t=sample/(FPS*SUB);
        const stepStart=performance.now();
        let bytes;
        if (direct && !fastPNG) {
          const encoded=await page.evaluate(async ([time,fmt])=>{
            await window.renderFrame(time);
            return window.filmCanvas.toDataURL(fmt,0.94).split(",")[1];
          },[t,SHOT_FMT==="png" ? "image/png" : "image/jpeg"]);
          bytes=Buffer.from(encoded,"base64");
          captureMs+=performance.now()-stepStart;
        } else {
          await page.evaluate((time)=>window.renderFrame(time),t);
          const captureStart=performance.now();
          sceneMs+=captureStart-stepStart;
          bytes=await page.screenshot({
            type:SHOT_FMT==="png" ? "png" : "jpeg",
            quality:SHOT_FMT==="png" ? undefined : 94,
            optimizeForSpeed:fastPNG,
            clip:{x:0,y:0,width:W,height:H},
          });
          captureMs+=performance.now()-captureStart;
        }
        return Buffer.from(bytes.buffer,bytes.byteOffset,bytes.byteLength);
      }
      for (let sample=start*SUB;sample<end;sample++) {
        const hold=holds.find(row=>row.start*SUB<=sample && sample<(row.start+row.frames)*SUB);
        if (hold!==activeHold) {
          activeHold=hold;
          still=undefined;
        }
        if (hold && !inspected.has(hold)) {
          const first=hold.start*SUB;
          const last=(hold.start+hold.frames)*SUB-1;
          const original=await capture(first);
          const agrees=(await capture(first+Math.floor((last-first)/2))).equals(original)
                        && (await capture(last)).equals(original);
          inspected.set(hold,agrees);
          if (agrees) {
            still=original;
            verifiedHolds++;
          } else rejectedHolds++;
        }
        if (inspected.get(hold)) {
          still ??= await capture(sample);
          reused++;
        }
        const bytes=still || await capture(sample);
        const pipeStart=performance.now();
        await push(bytes);
        pipeMs+=performance.now()-pipeStart;
        count++;
        if (count===1 || count%Math.max(1,Math.floor(TOTAL/10))===0 || count===TOTAL) {
          const seconds=(Date.now()-t0)/1000;
          say(`  ${count}/${TOTAL}  ${(seconds/count).toFixed(2)}s/帧  剩余 ~${(seconds/count*(TOTAL-count)).toFixed(0)}s`);
        }
      }
      timings.push({start,frames,seconds:(performance.now()-begin)/1000,
        sceneSeconds:direct && !fastPNG ? null : sceneMs/1000,
        captureSeconds:captureMs/1000,pipeSeconds:pipeMs/1000});
    }
    const draining=performance.now();
    proc.stdin.end();
    await done;
    fs.renameSync(output,OUT);
    if (metricsPath) fs.writeFileSync(metricsPath,JSON.stringify({
      setupSeconds:(ready-started)/1000,
      drainSeconds:(performance.now()-draining)/1000,
      ...(holdsPath ? {verifiedHolds,rejectedHolds,reusedSamples:reused} : {}),
      ranges:timings,
    }));
    if (holdsPath) console.log(JSON.stringify({verifiedHolds,rejectedHolds,reusedSamples:reused}));
  } finally {
    proc.stdin?.destroy();
    if (proc.exitCode === null) proc.kill();
    await browser.close();
    server.close();
  }
  } finally { fs.rmSync(fdir,{recursive:true,force:true}); }
}

function encoder(ctx, pipe) {
  const {SUB,FPS,fdir,firstSample,output}=ctx;
  const vf = [];
  if (SUB > 1) vf.push(
    `tmix=frames=${SUB},select='eq(mod(n,${SUB}),${SUB-1})',setpts=N/(${FPS}*TB),fps=${FPS}`
  );
  if (SCALE) vf.push(`scale=${SCALE}:flags=lanczos`);
  const pre = vf.length ? ["-vf", vf.join(",")] : [];
  const FFMPEG = process.env.FFMPEG_PATH || "ffmpeg";
  return spawn(FFMPEG, [
    "-y", "-v", "error", "-framerate", String(FPS * SUB),
    ...(pipe ? ["-f","image2pipe","-c:v",SHOT_FMT === "png" ? "png" : "mjpeg","-i","pipe:0"]
             : ["-start_number",String(firstSample),"-i",path.join(fdir,"%05d"+SHOT_EXT)]), ...pre,
    "-c:v", CODEC === "x265" ? "libx265" : "libx264",
    "-crf", String(CRF), "-preset", PRESET,
    ...(CODEC === "x265"
      ? ["-pix_fmt", "yuv420p10le", "-x265-params", "log-level=error:psy-rd=2.0:psy-rdoq=1.2:deblock=-1,-1"]
      : ["-pix_fmt", "yuv420p", "-tune", "film", "-profile:v", "high"]),
    "-color_primaries", "bt709", "-color_trc", "bt709", "-colorspace", "bt709",
    "-movflags", "+faststart", output,
  ], { stdio: [pipe ? "pipe" : "ignore", "inherit", "inherit"] });
}

function finished(proc) {
  return new Promise((ok, fail) => proc.once("error", fail).once("close", n =>
    n === 0 ? ok() : fail(new Error("ffmpeg exit " + n))));
}

main().then(() => {
  if (depsOut) fs.writeFileSync(depsOut, JSON.stringify(reusable ? Object.fromEntries(dependencies) : null));
}).catch(error => {
  if (QUIET) {
    say(error.stack || String(error));
    console.error(String(error.message || error).slice(0,700));
  } else console.error(error);
  process.exitCode=1;
}).finally(()=>{
  if (suppressedDiagnostics) console.error(`[page] ${suppressedDiagnostics} additional messages`);
  // Failed initial setup can leave a browser or server open.
  if (process.exitCode) process.exit(process.exitCode);
});
