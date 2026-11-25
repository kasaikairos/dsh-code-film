/** Shared camera basis for world projection, rays, and column-major WebGL matrices.
 * Angles are radians. Positive yaw turns toward +X; zero yaw faces +Z.
 */
const dot=(a,b)=>a.reduce((s,x,i)=>s+x*b[i],0);
const cross=([x,y,z],[a,b,c])=>[y*c-z*b,z*a-x*c,x*b-y*a];
const unit=v=>{const n=Math.hypot(...v);return v.map(x=>x/n);};

export function opticalCamera(eye,yaw,pitch,verticalFov,aspect) {
    if (eye.length!==3 || ![...eye,yaw,pitch,verticalFov,aspect].every(Number.isFinite) ||
        Math.abs(pitch)>=Math.PI/2 || verticalFov<=0 || verticalFov>=Math.PI || aspect<=0)
        throw new RangeError("invalid optical camera");
    const fwd=[Math.sin(yaw)*Math.cos(pitch),Math.sin(pitch),Math.cos(yaw)*Math.cos(pitch)];
    const right=unit(cross(fwd,[0,1,0]));
    const up=cross(right,fwd);
    const tanV=Math.tan(verticalFov/2),tanH=tanV*aspect;
    const view=new Float32Array([
        right[0],up[0],-fwd[0],0,
        right[1],up[1],-fwd[1],0,
        right[2],up[2],-fwd[2],0,
        -dot(right,eye),-dot(up,eye),dot(fwd,eye),1,
    ]);
    const projectDirection=dir=>{
        const z=dot(dir,fwd);
        return z>0?[dot(dir,right)/(z*tanH),dot(dir,up)/(z*tanV)]:null;
    };
    return {fwd,right,up,tanH,tanV,view,projectDirection,
        projectPoint:point=>projectDirection(point.map((x,i)=>x-eye[i])),
        ray:(x,y)=>unit(fwd.map((component,i)=>component+x*tanH*right[i]+y*tanV*up[i]))};
}

/** Planar mirror position for a distant source above horizontal water. */
export function flatWaterGlint(eye, direction, level=0) {
    if (direction[1]<=0 || eye[1]<=level) return null;
    const distance=(eye[1]-level)/direction[1];
    return [eye[0]+direction[0]*distance,level,eye[2]+direction[2]*distance];
}

export function angularDiameterPixels(diameter,verticalFov,height) {
    if (![diameter,verticalFov,height].every(Number.isFinite) ||
        diameter<=0 || diameter>=Math.PI || verticalFov<=0 || verticalFov>=Math.PI || height<=0)
        throw new RangeError("invalid angular scale");
    return height*Math.tan(diameter/2)/Math.tan(verticalFov/2);
}

/** Compare the GPU's actual column-major VP to the camera's analytic projection. */
export function auditProjection(camera, viewProjection, points, width, height) {
    let maxErrorPx=0;
    for (const point of points) {
        const [x,y,z]=point;
        const clip=[0,1,2,3].map(i=>x*viewProjection[i]+y*viewProjection[i+4]+
                                   z*viewProjection[i+8]+viewProjection[i+12]);
        const expected=camera.projectPoint(point);
        if (!expected || clip[3]<=0)
            throw new RangeError("projected point is behind the camera");
        maxErrorPx=Math.max(maxErrorPx,Math.hypot(
            (clip[0]/clip[3]-expected[0])*width*.5,
            (clip[1]/clip[3]-expected[1])*height*.5));
    }
    return maxErrorPx;
}
