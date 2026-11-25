"""Turn an original GLSL ES 3 fragment into a self-contained timeline HTML."""
import argparse
import json
from math import isfinite
from pathlib import Path

HEADER = """#version 300 es
precision highp float;
uniform vec2 resolution;
uniform float time;
out vec4 fragColor;
"""

PAGE = """<!doctype html>
<meta charset="utf-8">
<title>CodeFilm shader</title>
<style>
html,body{margin:0;overflow:hidden;background:#000}
canvas{display:block;width:100vw;height:100vh}
</style>
<canvas></canvas>
<script>
const fragment = __FRAGMENT__;
const duration = __DURATION__;
const canvas = document.querySelector("canvas");
try {
    const gl = canvas.getContext("webgl2", {antialias:false, alpha:false, preserveDrawingBuffer:true});
    if (!gl) throw new Error("WebGL2 unavailable");
    const vertex = `#version 300 es
    void main() {
        vec2 p = vec2((gl_VertexID << 1) & 2, gl_VertexID & 2);
        gl_Position = vec4(p*2.0-1.0,0.0,1.0);
    }`;
    function compile(kind, text) {
        const shader = gl.createShader(kind);
        gl.shaderSource(shader,text);
        gl.compileShader(shader);
        if (!gl.getShaderParameter(shader,gl.COMPILE_STATUS))
            throw new Error(gl.getShaderInfoLog(shader));
        return shader;
    }
    const program = gl.createProgram();
    gl.attachShader(program,compile(gl.VERTEX_SHADER,vertex));
    gl.attachShader(program,compile(gl.FRAGMENT_SHADER,fragment));
    gl.linkProgram(program);
    if (!gl.getProgramParameter(program,gl.LINK_STATUS)) throw new Error(gl.getProgramInfoLog(program));
    gl.useProgram(program);
    gl.bindVertexArray(gl.createVertexArray());
    const clock = gl.getUniformLocation(program,"time");
    const resolution = gl.getUniformLocation(program,"resolution");
    function draw(t) {
        if (gl.isContextLost()) throw new Error("WebGL context lost");
        const w=Math.round(innerWidth*devicePixelRatio), h=Math.round(innerHeight*devicePixelRatio);
        if (canvas.width!==w || canvas.height!==h) {
            canvas.width=w;
            canvas.height=h;
        }
        gl.viewport(0,0,w,h);
        gl.uniform2f(resolution,w,h);
        gl.uniform1f(clock,t);
        gl.drawArrays(gl.TRIANGLES,0,3);
    }
    draw(0);
    window.FILM = {duration};
    window.filmCanvas=canvas;
    window.filmCanvasOnly=true;
    window.renderFrame=draw;
    if (new URLSearchParams(location.search).get("preview")==="1") {
        const start=performance.now();
        function animate(now) {
            draw(((now-start)/1000)%duration);
            requestAnimationFrame(animate);
        }
        requestAnimationFrame(animate);
    }
} catch (error) {
    window.__FILM_ERROR__ = String(error);
    console.error(window.__FILM_ERROR__);
}
</script>
"""


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("fragment",type=Path)
    p.add_argument("--seconds",required=True,type=float)
    p.add_argument("--out",required=True,type=Path)
    a=p.parse_args()
    if not isfinite(a.seconds) or a.seconds<=0:
        p.error("seconds must be positive and finite")
    helpers = Path(__file__).with_name("optics.glsl").read_text(encoding="utf-8-sig")
    helpers += Path(__file__).with_name("dynamics.glsl").read_text(encoding="utf-8-sig")+"\n"
    source = a.fragment.read_text(encoding="utf-8-sig")
    fragment = HEADER + helpers + "\n#line 1 1\n" + source
    fragment += "\nvoid main(){ fragColor=vec4(filmToSrgb(shade(gl_FragCoord.xy)),1.0); }"
    literal=json.dumps(fragment,ensure_ascii=True).replace("<",r"\u003c")
    html=PAGE.replace("__DURATION__",str(a.seconds)).replace("__FRAGMENT__",literal)
    a.out.write_text(html,encoding="utf8")
    print(a.out)


if __name__=="__main__":
    main()
