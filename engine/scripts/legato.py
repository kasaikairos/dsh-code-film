"""Phrase-based sustained voices. Time is absolute seconds; durations are beats."""
import numpy as np

SR = 44100

def compose(seconds,bpm,cues):
    mix = np.zeros(round(seconds*SR), dtype=np.float32)
    beat = 60/bpm
    phrases = [c for c in cues if c.get("kind")=="phrase"]
    if not phrases:
        raise ValueError("legato requires phrase cues with notes")
    for cue in phrases:
        pos = round(SR*(float(cue["time"])+beat*cue.get("offset_beats",0)))
        line = []
        def emit():
            if not line:
                return
            durations = np.array([n for _,n in line])
            pitches = np.array([pitch for pitch,_ in line])
            edges = np.r_[0,np.cumsum(durations)]
            length = int(edges[-1])
            t = np.arange(length)/SR
            f = np.repeat(pitches,durations).astype(float)
            for i in range(1,len(line)):
                width = min(round(.045*SR),durations[i]//4)
                if width:
                    f[edges[i]:edges[i]+width] = np.linspace(pitches[i-1],pitches[i],width)
            drift = .09*np.sin(2*np.pi*4.65*t)*np.minimum(1,t/.5)
            phase = np.cumsum(2*np.pi*440/SR*2**((f+drift-69)/12))
            bow = cue.get("voice") in ("bow","horn")
            weights = (1,.39,.21,.11,.055) if bow else (1,.11,.19,.041)
            tone = sum(w*np.sin((i+1)*phase) for i,w in enumerate(weights))
            dur = length/SR
            env = np.sin(.25+2.55*t/dur)**.7
            env *= np.minimum(1,t/min(.13,dur/3))*np.minimum(1,(dur-t)/min(.26,dur/3))
            start = pos-length
            lo,hi = max(0,start),min(len(mix),pos)
            if hi>lo:
                mix[lo:hi] += (tone*env*cue.get("level",.19))[lo-start:hi-start]
            line.clear()
        for pitch,beats in cue["notes"]:
            if not np.isfinite(beats) or beats<=0: raise ValueError("invalid duration")
            n=max(1,round(beats*beat*SR))
            if pitch is None: emit()
            elif not 0<=pitch<=127: raise ValueError("invalid pitch")
            else: line.append((pitch,n))
            pos+=n
        emit()
    return mix/max(1,float(np.max(np.abs(mix)))/.92)

def phrase_score(seconds,bpm,seed,mood):
    # Generate a related family of phrases when a shot has no authored notes.
    rng=np.random.default_rng(seed)
    tonic=int(rng.choice([55,57,58,60]))
    scale=(0,2,3,5,7,8,10) if mood=="suspense" else (0,2,4,5,7,9,11)
    motif=[0,int(rng.choice([1,2])),int(rng.choice([3,4])),2]
    beat=60/bpm
    result=[]
    for bar,start in enumerate(np.arange(0,seconds,8*beat)):
        degrees=[x+(0,1,-1,0)[bar%4] for x in motif]
        if bar%4==3:
            degrees[-2:]=[1,0]
        rhythm=(1.5,1,1.5,2.5) if mood=="playful" else (2,1.5,1.5,2)
        notes=[[tonic+scale[n%7]+12*(n//7),b] for n,b in zip(degrees,rhythm)]
        result.append(dict(kind="phrase",time=float(start),voice="reed",notes=notes,level=.19))
        bass=(0,-3,-2,0)[bar%4]
        pitch=tonic-12+scale[bass%7]+12*(bass//7)
        result.append(dict(kind="phrase",time=float(start),voice="bow",
                           notes=[[pitch,4],[pitch+scale[2],3.4]],level=.095))
    return result
