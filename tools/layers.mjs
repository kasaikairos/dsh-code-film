/** Rebuild a static, object-local layer when its artwork or sample density changes. */
export function bakedLayer(paint) {
  let canvas, lastKey, lastDensity;
  return function draw(ctx, width, height, key, density=1) {
    if (![width,height,density].every(n => Number.isFinite(n) && n>0))
      throw new RangeError("invalid layer dimensions");
    const w=Math.ceil(width*density), h=Math.ceil(height*density);
    if (!canvas || canvas.width!==w || canvas.height!==h || key!==lastKey || density!==lastDensity) {
      const fresh=document.createElement("canvas");
      fresh.width=w; fresh.height=h;
      const g=fresh.getContext("2d");
      g.scale(w/width,h/height);
      paint(g,width,height);
      canvas=fresh; lastKey=key; lastDensity=density;
    }
    ctx.drawImage(canvas,0,0,width,height);
  };
}

/** Incoming shot is held at its opening pose until the timeline reaches its start. */
export function incomingTime(globalTime, start, opening=0) {
  return opening+Math.max(0,globalTime-start);
}
