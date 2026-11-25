"""Compile authored geometry or directional paint into production assets."""
import argparse
from html import escape
import json
from math import acos, atan2, ceil, cos, degrees, hypot, isfinite, pi, sin
from pathlib import Path
from random import Random
import re


def finite(values, count):
    if len(values)!=count or not all(map(isfinite,values)):
        raise ValueError(f"expected {count} finite numbers")
    return values


def perforated_panel(spec):
    """An exact cell partition of a rectangular solid minus rectangular apertures."""
    width,height,depth=finite(spec["size"],3)
    ox,oy,oz=finite(spec.get("pos",[0,0,0]),3)
    if min(width,height,depth)<=0:
        raise ValueError("panel dimensions must be positive")
    name=spec.get("name","panel")
    openings=[]
    for x,y,w,h in (finite(hole,4) for hole in spec["openings"]):
        if min(x,y)<0 or min(w,h)<=0 or x+w>width+1e-9 or y+h>height+1e-9:
            raise ValueError("opening must lie inside the panel")
        openings.append((x,y,min(width,x+w),min(height,y+h)))
    xs=sorted({0,width,*(x for a,_,b,_ in openings for x in (a,b))})
    objects=[]
    for left,right in zip(xs,xs[1:]):
        spans=sorted((low,high) for a,low,b,high in openings if a<right and b>left)
        cursor=0
        for low,high in [*spans,(height,height)]:
            if low>cursor+1e-10:
                objects.append({
                    "name":f"{name}_{len(objects)+1}","kind":"box",
                    "size":[right-left,low-cursor,depth],
                    "pos":[ox+(left+right-width)/2,oy+(cursor+low-height)/2,oz],
                    "mat":spec["mat"],"contact":False
                })
            cursor=max(cursor,high)
    return {"objects":objects}


def facade(spec):
    """Set the sill, frame and glazing inside real wall openings."""
    width,height,depth=finite(spec["size"],3)
    if depth<=0:
        raise ValueError("wall depth must be positive")
    ox,oy,oz=finite(spec.get("pos",[0,0,0]),3)
    name=spec.get("name","facade")
    windows=spec["windows"]
    openings=[finite(window["opening"],4) for window in windows]
    for i,(x,y,w,h) in enumerate(openings):
        if any(x<X+W and X<x+w and y<Y+H and Y<y+h for X,Y,W,H in openings[:i]):
            raise ValueError("facade windows must not overlap")
    objects=perforated_panel({**spec,"openings":openings})["objects"]
    for index,(window,(x,y,w,h)) in enumerate(zip(windows,openings)):
        frame=float(window.get("frame",min(w,h)*.065))
        inset=float(window.get("inset",depth*.72))
        if not 0<frame<min(w,h)*.25 or not 0<inset<depth:
            raise ValueError("frame or window inset is outside the opening")
        wx=ox+x+(w-width)*.5
        wy=oy+y+(h-height)*.5
        wall_front=oz+depth*.5
        wz=wall_front-inset
        frame_mat=window.get("frameMat",spec["frameMat"])
        pane_mat=window.get("paneMat",spec["paneMat"])
        front=min(inset*.7,frame)
        pane=min(frame*.1,(depth-inset)*.35)
        for suffix,cx,cy,cz,dimensions,mat in [
            ("jamb L",wx-(w-frame)/2,wy,wz,[frame,h,front],frame_mat),
            ("jamb R",wx+(w-frame)/2,wy,wz,[frame,h,front],frame_mat),
            ("head",wx,wy+(h-frame)/2,wz,[w-2*frame,frame,front],frame_mat),
            ("sash",wx,wy-(h-frame)/2,wz,[w-2*frame,frame,front],frame_mat),
            ("pane",wx,wy,wz-front/2-pane/2,[w-2*frame,h-2*frame,pane],pane_mat),
            ("sill",wx,wy-h/2-frame*.45,wall_front-inset*.2,
                [w+frame*1.5,frame*.9,inset*.65],window.get("sillMat",frame_mat)),
        ]:
            objects.append(dict(kind="box",name=f"{name} {index+1} {suffix}",
                pos=[cx,cy,cz],size=dimensions,mat=mat,contact=False))
    return {"objects":objects}


def plant(spec):
    """Build attached stems and leaf surfaces once, with one instanced foliage mesh."""
    height=float(spec["height"])
    spread=float(spec.get("spread",height*.65))
    count=int(spec.get("density",180))
    habit=spec.get("habit","tree")
    if not all(map(isfinite,(height,spread))) or min(height,spread)<=0 or not 6<=count<=1600:
        raise ValueError("plant requires positive height and spread, and density from 6 to 1600")
    if habit not in ("tree","grass"):
        raise ValueError("habit must be tree or grass")
    rng=Random(spec.get("seed",7))
    name=spec.get("name","plant")
    palette=spec.get("palette",["#405e2e","#597941","#708c46"])
    if not palette or any(not re.fullmatch(r"#[0-9a-fA-F]{6}",color) for color in palette):
        raise ValueError("palette must contain hex colors")
    pos=finite(spec.get("pos",[0,0,0]),3)
    parts=[]
    leaves=[]

    def rotation(direction):
        x,y,z=direction
        return [degrees(atan2(z,y)),0,degrees(atan2(-x,hypot(y,z)))]

    def stem(a,b,r1,r2):
        delta=[end-start for start,end in zip(a,b)]
        parts.append(dict(kind="cyl",name=f"{name} stem {len(parts)+1}",
            pos=[(start+end)/2 for start,end in zip(a,b)],rot=rotation(delta),
            h=hypot(*delta)+r2*.7,rBot=r1,rTop=r2,seg=9,
            mat=spec.get("bark",{"albedo":"#694e34","rough":.92}),contact=False))

    def leaf(origin,direction,length,width):
        leaves.append(dict(pos=origin,rot=rotation(direction),scale=[width,length,length],
            color=rng.choice(palette)))

    if habit=="grass":
        for i in range(count):
            az=rng.uniform(0,2*pi)
            radius=spread*.5*rng.random()**1.8
            h=height*rng.uniform(.35,1)
            tilt=rng.uniform(.10,.9)
            leaf([radius*cos(az),0,radius*sin(az)],[tilt*cos(az),1,tilt*sin(az)],
                 h,h*rng.uniform(.035,.09))
    else:
        trunk=[[0,0,0],[.018*spread,.37*height,0],[-.024*spread,.71*height,.038*spread],
               [.025*spread,height*.98,.012*spread]]
        trunk_radius=.041*height
        for i,(a,b) in enumerate(zip(trunk,trunk[1:])):
            stem(a,b,trunk_radius*(1-i*.30),trunk_radius*(.7-i*.29))
        twigs=[]
        for i in range(11):
            height_fraction=.36+i*.053
            low,high=(1,2) if height_fraction<.71 else (2,3)
            a0,a1=trunk[low],trunk[high]
            t=max(0,(height_fraction*height-a0[1])/(a1[1]-a0[1]))
            a=[x+(y-x)*t for x,y in zip(a0,a1)]
            az=i*2.399963+rng.uniform(-.2,.2)
            shoulder=max(0,1-((height_fraction-.56)/.54)**2)
            span=spread*shoulder*rng.uniform(.23,.38)
            b=[a[0]+span*cos(az),a[1]+height*rng.uniform(.06,.16),a[2]+span*sin(az)]
            stem(a,b,trunk_radius*(.41-.29*height_fraction),trunk_radius*.088)
            for j in (-1,0,1):
                t=rng.uniform(.55,.84) if j else .9
                start=[x+(y-x)*t for x,y in zip(a,b)]
                angle=az+j*rng.uniform(.52,1.42)
                reach=spread*rng.uniform(.10,.19)*shoulder
                tip=[start[0]+reach*cos(angle),min(1.04*height,start[1]+height*rng.uniform(.05,.16)),
                     start[2]+reach*sin(angle)]
                stem(start,tip,trunk_radius*.093,trunk_radius*.014)
                twigs.append((start,tip))
        for i in range(count):
            a,b=twigs[i%len(twigs)]
            frac=rng.uniform(.18,1)
            center=[x+(y-x)*frac for x,y in zip(a,b)]
            az=rng.uniform(0,2*pi)
            length=height*rng.uniform(.028,.067)
            leaf(center,[cos(az),rng.uniform(-.8,.55),sin(az)],length,
                 length*rng.uniform(.42,.76))
    foliage=dict(kind="instanced",base="leaf",name=f"{name} foliage",
        blade=habit=="grass",mat=dict(albedo="#ffffff",side="double",rough=.83),
        transforms=leaves,contact=False)
    if "wind" in spec:
        wind=spec["wind"]
        strength=float(wind["strength"])
        direction=finite(wind["direction"],2)
        if not 0<=strength<=.35 or hypot(*direction)==0:
            raise ValueError("wind strength must be 0–0.35 and direction must be nonzero")
        foliage["wind"]=dict(strength=strength,direction=direction)
    parts.append(foliage)
    return {"objects":[dict(kind="group",name=name,pos=pos,children=parts)]}


def turned_part(spec):
    """Revolve an authored silhouette, rounding profile corners and sizing tessellation."""
    profile=[finite(pair,2) for pair in spec["profile"]]
    if (len(profile)<3 or any(r<0 for r,y in profile)
        or any(b[1]<a[1] or a==b for a,b in zip(profile,profile[1:]))
        or not any(r>0 for r,y in profile)):
        raise ValueError("lathe profile needs distinct [radius,height] points ordered bottom to top")
    radius=float(spec.get("corner",0))
    pixels=float(spec["radiusPx"])
    tolerance=float(spec.get("errorPx",.4))
    if not all(map(isfinite,(radius,pixels,tolerance))) or radius<0 or min(pixels,tolerance)<=0:
        raise ValueError("invalid corner, projected radius or error")
    rounded=[profile[0]]
    for a,b,c in zip(profile,profile[1:],profile[2:]):
        left=hypot(b[0]-a[0],b[1]-a[1])
        right=hypot(c[0]-b[0],c[1]-b[1])
        cut=min(radius,left*.45,right*.45)
        if not cut or not b[0]:
            rounded.append(b)
            continue
        first=[y+(x-y)*cut/left for x,y in zip(a,b)]
        last=[y+(z-y)*cut/right for y,z in zip(b,c)]
        for i in range(5):
            t=i/4
            rounded.append([(1-t)**2*x+2*t*(1-t)*y+t*t*z for x,y,z in zip(first,b,last)])
    rounded.append(profile[-1])
    # Screen-space sagitta: r * (1 - cos(pi/n)).
    requested=ceil(pi/acos(max(-1,1-tolerance/pixels))) if tolerance/pixels>1e-10 else 193
    segments=max(12,min(192,requested))
    part={"kind":"lathe","name":spec.get("name","lathe"),"profile":rounded,"seg":segments,
          "pos":finite(spec.get("pos",[0,0,0]),3),"mat":spec["mat"]}
    return {"objects":[part],"estimatedErrorPx":pixels*(1-cos(pi/segments))}


def pigment(spec):
    """A vector paint layer with seeded strokes aligned to an authored field."""
    width,height=finite(spec["size"],2)
    if min(width,height)<=0:
        raise ValueError("painting dimensions must be positive")
    palette=spec["palette"]
    if len(palette)<2 or not all(re.fullmatch(r"#[\da-fA-F]{6}",p) for p in palette):
        raise ValueError("palette must contain at least two six-digit hex colors")
    polygon=spec.get("clip",[[0,0],[1,0],[1,1],[0,1]])
    if len(polygon)<3:
        raise ValueError("clip requires three normalized points")
    points=" ".join(f"{x*width:.3f},{y*height:.3f}" for x,y in (finite(p,2) for p in polygon))
    seed=spec.get("seed",1)
    rng=Random(seed)
    ax,ay=finite(spec["flow"],2)
    if hypot(ax,ay)==0:
        raise ValueError("flow cannot be zero")
    warp=float(spec.get("warp",.35))
    if not isfinite(warp) or abs(warp)>1:
        raise ValueError("warp must be in [-1,1]")
    budgets=spec.get("strokes",[120,280,480])
    if len(budgets)!=3 or any(type(n) is not int or n<0 for n in budgets) or sum(budgets)>5000:
        raise ValueError("supply three stroke counts, total at most 5000")
    identifier=escape(spec.get("id","pigment"),quote=True)
    stops="".join(f'<stop offset="{i/(len(palette)-1):.4f}" stop-color="{c}"/>'
                  for i,c in enumerate(palette))
    result=[f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}">',
            f'<defs><clipPath id="{identifier}-mask"><polygon points="{points}"/></clipPath>',
            f'<linearGradient id="{identifier}-base" x2="0" y2="1">{stops}</linearGradient></defs>',
            f'<g clip-path="url(#{identifier}-mask)">',
            f'<rect width="{width}" height="{height}" fill="url(#{identifier}-base)"/>']
    scale=min(width,height)
    for length, count, stroke_width in zip((.14,.065,.026),budgets,(.036,.012,.004)):
        for _ in range(count):
            u,v=rng.random(),rng.random()
            x,y=u*width,v*height
            # The same directional function controls the center and tip of each stroke.
            def direction(s,t):
                dx=ax+warp*sin(2*pi*(t+.7*s))
                dy=ay+warp*cos(2*pi*(s-.6*t))
                norm=hypot(dx,dy) or 1
                return dx/norm,dy/norm
            dx,dy=direction(u,v)
            span=length*scale*(.6+.8*rng.random())
            mx,my=x+dx*span*.5,y+dy*span*.5
            ex,ey=direction(mx/width,my/height)
            endx,endy=mx+ex*span*.5,my+ey*span*.5
            tone=max(0,min(len(palette)-1,round((v+rng.uniform(-.28,.28))*(len(palette)-1))))
            result.append(f'<path d="M{x:.2f} {y:.2f} Q{mx:.2f} {my:.2f} {endx:.2f} {endy:.2f}" '
                          f'fill="none" stroke="{palette[tone]}" stroke-width="{stroke_width*scale:.2f}" '
                          f'stroke-linecap="round" opacity="{rng.uniform(.18,.68):.2f}"/>')
    result.append("</g></svg>")
    return "\n".join(result)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("spec",type=Path)
    parser.add_argument("--out",required=True,type=Path)
    parser.add_argument("--scene",type=Path,help="append 3D geometry to a copy of this space scene")
    args=parser.parse_args()
    try:
        spec=json.loads(args.spec.read_text(encoding="utf-8-sig"))
        if spec["kind"]=="panel":
            data=perforated_panel(spec)
            output=json.dumps(data,ensure_ascii=False,indent=2)
            summary=f"{len(data['objects'])} box solids"
        elif spec["kind"] in ("facade","plant"):
            data=facade(spec) if spec["kind"]=="facade" else plant(spec)
            output=json.dumps(data,ensure_ascii=False,separators=(",",":"))
            summary=f"{spec['kind']} geometry"
        elif spec["kind"]=="lathe":
            data=turned_part(spec)
            output=json.dumps(data,ensure_ascii=False,indent=2)
            summary=f"{data['objects'][0]['seg']} segments | estimated error {data['estimatedErrorPx']:.3f}px"
        elif spec["kind"]=="pigment":
            output=pigment(spec)
            summary="1 reusable vector paint layer"
        else:
            raise ValueError("kind must be panel, facade, plant, lathe or pigment")
        if args.scene:
            if spec["kind"]=="pigment" or args.scene.resolve()==args.out.resolve():
                raise ValueError("--scene requires 3D geometry and a separate output path")
            scene=json.loads(args.scene.read_text(encoding="utf-8-sig"))
            if scene.get("template")!="space":
                raise ValueError("--scene expects a space scene")
            scene.setdefault("objects",[]).extend(data["objects"])
            output=json.dumps(scene,ensure_ascii=False,separators=(",",":"))
        args.out.write_text(output+"\n",encoding="utf8")
    except (ValueError,TypeError,KeyError,OSError) as exc:
        parser.exit(1,str(exc)[:400]+"\n")
    print(f"{summary} | {args.out}")


if __name__=="__main__":
    main()
