/** Paint an original, code-drawn opaque canvas into a reusable object-local layer. */
export function brushLayer(source, {sizes, seed = 1, direction} = {}) {
  const {width, height} = source;
  const output = document.createElement("canvas");
  output.width = width;
  output.height = height;
  const ctx = output.getContext("2d");
  ctx.drawImage(source, 0, 0);
  const pixels = ctx.getImageData(0, 0, width, height).data;
  const index = (x,y) => 4 * (Math.min(height-1, Math.max(0, Math.round(y))) * width +
                              Math.min(width-1, Math.max(0, Math.round(x))));
  const luminance = (x,y) => {
    const i = index(x,y);
    return pixels[i]*0.213 + pixels[i+1]*0.715 + pixels[i+2]*0.072;
  };
  const random = () => ((seed = (Math.imul(seed, 1664525) + 1013904223) >>> 0) / 4294967296);
  const scale = Math.min(width,height);
  const passes = sizes ?? [scale/35, scale/85, scale/180];
  if (!passes.every(r => Number.isFinite(r) && r >= 1)) {
    if (sizes) throw new RangeError("brush sizes must be at least one pixel");
  }
  for (const radius of passes) {
    const r = Math.max(1,radius);
    for (let y=0; y<height; y+=r) for (let x=0; x<width; x+=r) {
      const px=x+random()*r, py=y+random()*r;
      const dx=luminance(px+r,py)-luminance(px-r,py);
      const dy=luminance(px,py+r)-luminance(px,py-r);
      const edge=Math.hypot(dx,dy);
      if (radius!==passes[0] && edge<8 && random()>0.12) continue;
      const angle=direction?.(px,py,r) ?? (edge>3 ? Math.atan2(dy,dx)+Math.PI/2 : 0);
      const a=angle+(random()-0.5)*0.28;
      const i=index(px,py), shift=(random()-0.5)*13;
      ctx.fillStyle='rgb('+[0,1,2].map(c=>Math.round(pixels[i+c]+shift)).join(',')+')';
      ctx.save();
      ctx.translate(px,py);
      ctx.rotate(a);
      ctx.beginPath();
      ctx.moveTo(-1.6*r,0);
      ctx.quadraticCurveTo(-0.2*r,-0.8*r,1.7*r,-0.15*r);
      ctx.quadraticCurveTo(0.3*r,0.55*r,-1.6*r,0);
      ctx.fill();
      ctx.restore();
    }
  }
  return output;
}
