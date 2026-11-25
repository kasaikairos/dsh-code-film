/** Bounded visual flow and deterministic, seekable advection. Coordinates are X/Z. */
export function aroundCircle(point, center, radius, flow) {
    const x=point[0]-center[0], z=point[1]-center[1];
    const length=Math.hypot(x,z);
    if (length<radius || !(radius>0)) throw new RangeError("sample must be outside flow obstacle");
    const nx=x/length,nz=z/length;
    const scale=(radius/length)**2;
    const radial=flow[0]*nx+flow[1]*nz;
    return [(1+scale)*flow[0]-2*scale*radial*nx,
            (1+scale)*flow[1]-2*scale*radial*nz];
}

export function bakeDrift(field, startPoint, duration, hz=60) {
    if (startPoint.length!==2 || ![...startPoint,duration,hz].every(Number.isFinite) ||
        duration<=0 || hz<=0 || Math.ceil(duration*hz)>36000) throw new RangeError("invalid drift schedule");
    const count=Math.ceil(duration*hz), h=duration/count;
    const points=[startPoint.slice()], velocities=[];
    for (let i=0;i<=count;i++){
        const t=i*h,p=points[i];
        const v=field(p,t);
        if(v.length!==2 || !v.every(Number.isFinite))throw new RangeError("invalid field velocity");
        velocities.push(v.slice());
        if (i===count)break;
        const middle=field(p.map((x,j)=>x+.5*h*v[j]),t+.5*h);
        if(middle.length!==2 || !middle.every(Number.isFinite))throw new RangeError("invalid midpoint velocity");
        points.push(p.map((x,j)=>x+h*middle[j]));
    }
    return function at(time) {
        if(!Number.isFinite(time))throw new RangeError("invalid drift time");
        const step=Math.max(0,Math.min(count,time/h));
        const i=Math.min(count-1,Math.floor(step)), u=step-i;
        const p=points[i], q=points[i+1];
        const a=velocities[i], b=velocities[i+1];
        const position=p.map((x,j)=>(1-u)**2*((1+2*u)*x+u*h*a[j])+
                               u*u*((3-2*u)*q[j]+(u-1)*h*b[j]));
        const velocity=p.map((x,j)=>6*u*(1-u)*(q[j]-x)/h+
                               (1-4*u+3*u*u)*a[j]+(3*u*u-2*u)*b[j]);
        return {position,velocity};
    };
}

/** GLSL vertex helpers. Same moving field at the same world point across materials. */
export const windGLSL=`
vec2 filmWind(vec2 worldXZ,float t,vec2 axis,float strength) {
    float phase=dot(worldXZ,axis)*1.3-t*1.55;
    float packet=0.32+0.68*pow(0.5+0.5*sin(phase),2.0);
    float flutter=0.12*sin(2.63*phase+worldXZ.x*.78);
    return strength*(axis*packet+vec2(-axis.y,axis.x)*flutter);
}
vec2 filmRootBend(vec2 wind,float height01,float compliance) {
    float y=clamp(height01,0.0,1.0);
    return wind*compliance*y*y;
}
`;
