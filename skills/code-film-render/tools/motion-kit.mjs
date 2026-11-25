/** Absolute-time functions for reproducible previews and final renders. */
export function travel(time, start, duration) {
    if (![time,start,duration].every(Number.isFinite) || duration<=0)
        throw new RangeError("travel requires finite time, start and positive duration");
    const u=Math.max(0,Math.min(1,(time-start)/duration));
    return u*u*u*(10+u*(-15+6*u));
}

export function recoil(time, at, decay, hz, amplitude=1) {
    if (![time,at,decay,hz,amplitude].every(Number.isFinite) || decay<=0 || hz<=0)
        throw new RangeError("recoil requires positive decay and frequency");
    const elapsed=time-at;
    return elapsed<=0 ? 0 : amplitude*Math.exp(-decay*elapsed)*Math.sin(2*Math.PI*hz*elapsed);
}

/** Keep both links rigid while approaching a target from a chosen bend side. */
export function reach2D(origin, target, upper, lower, bend=1) {
    if (![...origin,...target,upper,lower].every(Number.isFinite) ||
        origin.length!==2 || target.length!==2 || Math.min(upper,lower)<=0 ||
        Math.abs(bend)!==1)
        throw new RangeError("invalid limb geometry");
    const dx=target[0]-origin[0], dy=target[1]-origin[1];
    const length=Math.hypot(dx,dy);
    const axis=length>0 ? [dx/length,dy/length] : [1,0];
    const span=Math.max(Math.abs(upper-lower),Math.min(upper+lower,length));
    const along=span>0 ? (span*span+(upper-lower)*(upper+lower))/(2*span) : 0;
    const side=bend*Math.sqrt(Math.max(0,upper*upper-along*along));
    return {
        joint:[origin[0]+axis[0]*along-axis[1]*side,origin[1]+axis[1]*along+axis[0]*side],
        end:[origin[0]+axis[0]*span,origin[1]+axis[1]*span],
        gap:Math.abs(length-span)
    };
}

/** Scalar authored track. Monotone cubic segments share velocity at each key.
 * A hold is two equal-valued keys. A key with rest:true sets velocity to zero.
 */
export function motionTrack(keys) {
    if (keys.length<2 || keys.some(({t,value},i)=>
        !Number.isFinite(t) || !Number.isFinite(value) || (i>0 && t<=keys[i-1].t)))
        throw new RangeError("track needs at least two finite, increasing keys");
    const times=keys.map(key=>key.t), values=keys.map(key=>key.value);
    const widths=times.slice(1).map((t,i)=>t-times[i]);
    const slopes=widths.map((h,i)=>(values[i+1]-values[i])/h);
    const tangents=keys.map((key,i)=>{
        const a=slopes[i-1], b=slopes[i];
        if (key.rest || !a || !b || Math.sign(a)!==Math.sign(b)) return 0;
        const w1=2*widths[i]+widths[i-1], w2=widths[i]+2*widths[i-1];
        return (w1+w2)/(w1/a+w2/b);
    });
    return function at(time) {
        if (!Number.isFinite(time)) throw new RangeError("invalid sample time");
        if (time<=times[0]) return values[0];
        const last=times.length-1;
        if (time>=times[last]) return values[last];
        let lo=0, hi=last;
        while (hi-lo>1) {
            const mid=(lo+hi)>>1;
            if (times[mid]<=time) lo=mid;
            else hi=mid;
        }
        const h=widths[lo], u=(time-times[lo])/h;
        return (1-u)**2*((1+2*u)*values[lo]+u*h*tangents[lo])+
            u*u*((3-2*u)*values[hi]+(u-1)*h*tangents[hi]);
    };
}

/** Join two ongoing paths of the same landmark or scene parameter.
 * Both tracks evaluate absolute time and use one common coordinate system.
 */
export function handoff(from, to, start, duration) {
    if (typeof from!=="function" || typeof to!=="function" ||
        ![start,duration].every(Number.isFinite) || duration<=0)
        throw new RangeError("handoff needs two paths and a positive duration");
    return function at(time) {
        const w=travel(time,start,duration);
        if (w===0) return from(time);
        if (w===1) return to(time);
        const a=from(time), b=to(time);
        if (Number.isFinite(a) && Number.isFinite(b)) return a+w*(b-a);
        if (!Array.isArray(a) || !Array.isArray(b) || !a.length || a.length!==b.length ||
            !a.every(Number.isFinite) || !b.every(Number.isFinite))
            throw new RangeError("handoff paths must return matching finite states");
        return a.map((value,i)=>value+w*(b[i]-value));
    };
}

/** Drive an occlusion/reveal edge in the same coordinate system as the object.
 * In a shader, weight = 1 - smoothstep(edge - feather, edge + feather, field).
 * Supply bounded values for field so both endpoint states are fully visible.
 */
export function revealTrack(start, duration, bounds, feather) {
    const [low,high]=bounds;
    if (![start,duration,low,high,feather].every(Number.isFinite) ||
        duration<=0 || high<=low || feather<=0)
        throw new RangeError("reveal needs increasing bounds and positive duration and feather");
    return time=>low-feather+(high-low+2*feather)*travel(time,start,duration);
}

/** A delayed critically damped response to an authored scalar driver.
 * The solver runs once. Render and audit then read the same time function.
 */
export function followThrough(driver, {start,end,frequency=3,delay=0}) {
    if (typeof driver!=="function" ||
        ![start,end,frequency,delay].every(Number.isFinite) ||
        end<=start || frequency<=0 || frequency>20 || delay<0 || end-start>600)
        throw new RangeError("invalid response interval, delay or frequency");
    const steps=Math.ceil((end-start)*120), h=(end-start)/steps;
    const rate=frequency*2*Math.PI, decay=Math.exp(-rate*h);
    const positions=new Float64Array(steps+1), velocities=new Float64Array(steps+1);
    positions[0]=driver(start-delay);
    if (!Number.isFinite(positions[0])) throw new RangeError("driver must be finite");
    for (let i=0;i<steps;i++) {
        const target=driver(start+(i+.5)*h-delay);
        if (!Number.isFinite(target)) throw new RangeError("driver must be finite");
        const x=positions[i]-target, v=velocities[i], q=v+rate*x;
        positions[i+1]=target+(x+q*h)*decay;
        velocities[i+1]=(v-rate*q*h)*decay;
    }
    return time=>{
        if (!Number.isFinite(time)) throw new RangeError("sample time must be finite");
        if (time<=start) return positions[0];
        if (time>=end) return positions[steps];
        const sample=(time-start)/h, i=Math.min(steps-1,Math.floor(sample)), u=sample-i;
        return (1-u)**2*((1+2*u)*positions[i]+u*h*velocities[i])+
            u*u*((3-2*u)*positions[i+1]+(u-1)*h*velocities[i+1]);
    };
}
