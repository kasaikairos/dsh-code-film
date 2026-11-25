import fs from "node:fs";
import path from "node:path";
import {createRequire} from "node:module";
import {pathToFileURL} from "node:url";
const [cache,html,...args]=process.argv.slice(2);
const sourceOnly = args.includes("--source-only");
const raw = args.filter(arg => arg !== "--source-only");
if (sourceOnly && raw[0] === "--profile")
  throw Error("run --source-only with time samples, and --profile in a separate check");
const profile = raw[0] === "--profile" ? JSON.parse(fs.readFileSync(raw[1], "utf8").replace(/^\uFEFF/, "")) : null;
const limits = ["minSpread", "maxClipped", "minDetailCoverage", "maxGrain", "maxFlicker"];
if (profile && (!Array.isArray(profile.samples) || !profile.samples.length ||
    profile.samples.some(row => !limits.some(key => key in row) ||
      limits.some(key => key in row && (!Number.isFinite(row[key]) || row[key] < 0 || row[key] > 1)) ||
      ("maxFlicker" in row && (!Number.isFinite(row.compareTime) || row.compareTime < 0 ||
                              row.compareTime === row.time))))) {
  throw Error("invalid visual profile");
}
const times=profile ? [...new Set(profile.samples.flatMap(row =>
  "maxFlicker" in row ? [row.time, row.compareTime] : [row.time]))] : raw.map(Number);
if(!html || !times.length || times.some(t=>!Number.isFinite(t)||t<0))
  throw Error("preflight index.html seconds [seconds ...]");
const req=createRequire(path.join(cache,"package.json"));
const {default:puppeteer}=await import(pathToFileURL(req.resolve("puppeteer")));
const {servePage}=await import(pathToFileURL(path.join(cache,"scripts/page_server.mjs")));
const server=await servePage(html, null, { sourceOnly });
let browser;
try {
  browser=await puppeteer.launch({executablePath:process.env.PUPPETEER_EXECUTABLE_PATH,headless:true});
  const page=await browser.newPage();
  const [width,height]=profile?.viewport ?? [1920,1080];
  if (![width,height].every(n => Number.isInteger(n) && n >= 16 && n <= 4096))
    throw Error("invalid profile viewport");
  await page.setViewport({width,height});
  const external = new Set();
  if (sourceOnly) {
    const origin = "http://127.0.0.1:" + server.address().port;
    await page.setRequestInterception(true);
    page.on("request", request => {
      const url = new URL(request.url());
      if (url.origin === origin && url.protocol === "http:") return request.continue();
      external.add(url.protocol + (url.host ? "//" + url.host : ""));
      return request.abort("blockedbyclient");
    });
    await page.evaluateOnNewDocument(() => {
      const blocked = new Set();
      window.collectSourceViolations = () => [...blocked];
      document.addEventListener("securitypolicyviolation", event => {
        if (event.blockedURI.endsWith("/favicon.ico")) return;
        // Avoid returning large inline payloads to the model.
        blocked.add(event.effectiveDirective + " " + event.blockedURI.slice(0, 140));
      });
    });
  }
  async function checkSources() {
    if (!sourceOnly) return;
    const blocked = [...external, ...server.blockedSources, ...await page.evaluate(() => window.collectSourceViolations?.() || [])];
    if (blocked.length) throw Error("source-only blocked: " + blocked.slice(0, 4).join(", "));
  }
  await page.goto("http://127.0.0.1:"+server.address().port+"/"+encodeURIComponent(path.basename(html))+"?render=1");
  await checkSources();
  await page.waitForFunction(()=>window.__FILM_ERROR__||window.__RENDER__?.setTime||
    window.__FILM__?.renderAt||window.renderFrame);
  async function screenshotAt(time) {
    await page.evaluate(async t=>{
      if(window.__RENDER__?.setTime) await window.__RENDER__.setTime(t);
      else if(window.renderFrame) await window.renderFrame(t);
      else await window.__FILM__.renderAt(t);
    },time);
    return page.screenshot({encoding:"base64"});
  }
  const issue=await page.evaluate(async times=>{
    if(window.__FILM_ERROR__||window.__RENDER__?.missing?.length) return "load: "+String(window.__FILM_ERROR__||window.__RENDER__.missing).slice(0,250);
    const proto=CanvasRenderingContext2D.prototype, depths=new Map();
    let underflow=false;
    for(const [key,step] of [["save",1],["restore",-1]]){
      const original=proto[key];
      proto[key]=function(...args){
        if(this.canvas.isConnected){
          const next=(depths.get(this)||0)+step;
          underflow ||= next<0;
          depths.set(this,next);
        }
        return original.apply(this,args);
      }
    }
    for(const t of times){
      if(window.__RENDER__?.setTime) await window.__RENDER__.setTime(t);
      else if(window.renderFrame) await window.renderFrame(t);
      else await window.__FILM__.renderAt(t);
      if(underflow||[...depths.values()].some(d=>d!==0))return "unbalanced Canvas state at "+t+"s";
    }
  },times);
  await checkSources();
  if(issue) throw Error(issue);
  if (profile) {
    for (const {time,minSpread,maxClipped,minDetailCoverage,maxGrain,maxFlicker,compareTime,
                roi=[0,0,1,1]} of profile.samples) {
      const [x,y,w,h]=roi;
      if (![x,y,w,h].every(Number.isFinite) || x<0 || y<0 || w<=0 || h<=0 || x+w>1 || y+h>1)
        throw Error("invalid normalized ROI");
      const png=await screenshotAt(time);
      const compare=maxFlicker === undefined ? null : await screenshotAt(compareTime);
      const metrics=await page.evaluate(async ({png,compare,measureGrain,x,y,w,h})=>{
        async function decode(source) {
          const image=new Image();
          image.src="data:image/png;base64,"+source;
          await image.decode();
          return image;
        }
        const img=await decode(png);
        const result={};
        if (measureGrain || compare) {
          const canvas=document.createElement("canvas");
          canvas.width=Math.round((x+w)*img.width)-Math.round(x*img.width);
          canvas.height=Math.round((y+h)*img.height)-Math.round(y*img.height);
          if (canvas.width<3 || canvas.height<3) throw Error("noise ROI needs at least 3 × 3 pixels");
          const context=canvas.getContext("2d",{willReadFrequently:true});
          const pixelsAt=image=>{
            context.clearRect(0,0,canvas.width,canvas.height);
            context.drawImage(image,-Math.round(x*img.width),-Math.round(y*img.height));
            return context.getImageData(0,0,canvas.width,canvas.height).data;
          };
          const first=pixelsAt(img);
          const second=compare ? pixelsAt(await decode(compare)) : null;
          const stride=4*canvas.width;
          if (measureGrain) {
            let energy=0;
            for (let row=1;row<canvas.height-1;row++) for (let col=1;col<canvas.width-1;col++) {
              const offset=row*stride+4*col;
              for (let c=offset;c<offset+3;c++)
                energy+=(first[c]-(first[c-4]+first[c+4]+first[c-stride]+first[c+stride])/4)**2;
            }
            result.grain=Math.sqrt(energy/(3*(canvas.width-2)*(canvas.height-2)))/255;
          }
          if (second) {
            let energy=0;
            for (let i=0;i<first.length;i+=4) for (let c=i;c<i+3;c++)
              energy+=(first[c]-second[c])**2;
            result.flicker=Math.sqrt(energy/(first.length*.75))/255;
          }
        }
        const c=document.createElement("canvas");
        c.width=c.height=96;
        const g=c.getContext("2d");
        g.drawImage(img,x*img.width,y*img.height,w*img.width,h*img.height,0,0,96,96);
        const pixels=g.getImageData(0,0,96,96).data;
        const values=[];
        for(let i=0;i<pixels.length;i+=4)
          values.push((.2126*pixels[i]+.7152*pixels[i+1]+.0722*pixels[i+2])/255);
        // Ignore isolated edges: a tile needs repeated fine variation, and
        // a coarser variation in the same tile, to count toward coverage.
        let detailed=0;
        for(let y=0;y<96;y+=12) for(let x=0;x<96;x+=12) {
          let fine=0, coarse=0;
          for(let j=y;j<y+8;j++) for(let i=x;i<x+8;i++){
            const k=j*96+i;
            for(const stride of [1,96]) {
              const a=values[k], b=values[k+stride], c=values[k+2*stride], d=values[k+3*stride];
              fine+=Math.abs(a-b)>.02;
              coarse+=Math.abs((a+b-c-d)*.5)>.035;
            }
          }
          detailed+=fine>=20 && coarse>=16;
        }
        values.sort((a,b)=>a-b);
        const q=p=>values[Math.floor(p*(values.length-1))];
        return {...result,detailCoverage:detailed/64,spread:q(.9)-q(.1),clipped:values.filter(v=>v<=.01||v>=.99).length/values.length};
      },{png,compare,measureGrain:maxGrain!==undefined,x,y,w,h});
      const failed=metrics.spread<(minSpread??0) || metrics.clipped>(maxClipped??1) ||
          metrics.detailCoverage<(minDetailCoverage??0) || metrics.grain>maxGrain ||
          metrics.flicker>maxFlicker;
      if (failed || maxGrain!==undefined || maxFlicker!==undefined)
        (failed ? console.error : console.log)(JSON.stringify({time,compareTime,roi,...metrics,
          minSpread,maxClipped,minDetailCoverage,maxGrain,maxFlicker}));
      if (failed) {
        process.exitCode=1;
        break;
      }
    }
  }
  if (!process.exitCode) console.log(times.length+" sampled times passed");
} finally {try{await browser?.close()}finally{server.close()}}
