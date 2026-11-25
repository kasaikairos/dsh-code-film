/** Build original albedo and optional relief maps once, at the artist's chosen resolution. */
import * as THREE from "three";

function paintedMap(width, height, draw, colorSpace) {
  const canvas = document.createElement("canvas");
  canvas.width = width;
  canvas.height = height;
  draw(canvas.getContext("2d"), width, height);
  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = colorSpace;
  texture.anisotropy = 4;
  return texture;
}

export function paintedSurface({width, height, paint, relief, bumpScale = 0.001, ...material}) {
  if (![width,height].every(x => Number.isSafeInteger(x) && x > 0)) {
    throw new TypeError("surface width and height must be positive integer pixels");
  }
  const surface = new THREE.MeshStandardMaterial(material);
  surface.map = paintedMap(width, height, paint, THREE.SRGBColorSpace);
  if (relief) {
    surface.bumpMap = paintedMap(width, height, relief, THREE.NoColorSpace);
    surface.bumpScale = bumpScale;
  }
  return surface;
}
/** Sample one authored physical field once per texel. The same UV controls
 * reflectance and relief; e.g. a polished contact band may also be worn down.
 * G stores roughness, B metalness, R stores height for the bump sampler. */
export function materialField({width, height, sample, bumpScale = 0.001, ...options}) {
  const packed = paintedMap(width, height, (ctx,w,h) => {
    const image = ctx.createImageData(w,h);
    for (let y=0; y<h; y++) for (let x=0; x<w; x++) {
      const {height: relief, roughness, metalness} = sample((x+0.5)/w,(y+0.5)/h);
      const i=4*(y*w+x);
      image.data[i]=255*relief;
      image.data[i+1]=255*roughness;
      image.data[i+2]=255*metalness;
      image.data[i+3]=255;
    }
    ctx.putImageData(image,0,0);
  }, THREE.NoColorSpace);
  return new THREE.MeshStandardMaterial({...options, bumpScale, roughness:1, metalness:1,
    bumpMap:packed, roughnessMap:packed, metalnessMap:packed});
}
