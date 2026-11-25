"""Synthesize event-bound stereo Foley and optionally mix an authored music stem."""
import argparse
import json
import math
from pathlib import Path
import wave
import zlib

import numpy as np


SR=44100
IMPACTS={
    "wood":((146,319,660),34,1450),
    "metal":((343,781,1269),21,2100),
    "stone":((206,464,927),49,1850),
    "soft":((82,127,232),58,860),
}
SURFACES={
    "fabric":(170,1500),
    "paper":(440,2200),
    "wood":(108,950),
    "gravel":(270,1850),
}
BEDS={"air":(42,530),"water":(100,1280)}


def noise(rng,count,low,high):
    spectrum=np.fft.rfft(rng.standard_normal(count,dtype=np.float32))
    hz=np.fft.rfftfreq(count,1/SR)
    band=(-np.expm1(-(hz/low)**2))*np.exp(-(hz/high)**4)
    return np.fft.irfft(spectrum*band,n=count).astype(np.float32)


def ease(x):
    x=np.clip(x,0,1)
    return x*x*(3-2*x)


def resolve(cue,key,events):
    value=cue[key]
    if isinstance(value,str):
        if value not in events:
            if cue.get("optional"):
                return None
            raise ValueError(f"missing event {value}")
        value=events[value]
    if not isinstance(value,(int,float)) or not math.isfinite(value):
        raise ValueError("sound times must be finite seconds or event names")
    return float(value)


def effect(cue,start,end,seed):
    rng=np.random.default_rng(seed)
    count=max(2,round((end-start)*SR))
    t=np.arange(count,dtype=np.float32)/SR
    kind=cue["kind"]
    if kind=="contact":
        modes,decay,cutoff=IMPACTS[cue.get("material","wood")]
        signal=.62*noise(rng,count,180,cutoff)*np.exp(-t*112)
        for rank,hz in enumerate(modes):
            signal+=(.58/(1+rank))*np.sin(t*(2*np.pi*hz))*np.exp(-t*(decay+9*rank))
        envelope=ease(t/.004)*ease((end-start-t)/.03)
    else:
        band=SURFACES[cue.get("material","fabric")] if kind=="friction" else BEDS[kind]
        signal=noise(rng,count,*band)
        if kind=="water":
            signal*=.73+.27*np.sin(t*2*np.pi*1.4+.7)
        elif kind=="air":
            signal*=.77+.23*np.sin(t*2*np.pi*.62+1.9)
        edge=min((end-start)*.35,.24 if kind in BEDS else .08)
        envelope=ease(t/edge)*ease((end-start-t)/edge)
    return signal*envelope


def design(document):
    seconds=float(document["seconds"])
    if not math.isfinite(seconds) or seconds<=0 or round(seconds*SR)<2:
        raise ValueError("seconds must be positive")
    count=round(seconds*SR)
    events=document.get("events",{})
    stereo=np.zeros((count,2),dtype=np.float32)
    duck=np.zeros(count,dtype=np.float32)
    used=[]
    ids=set()
    for cue in document["sounds"]:
        identifier=cue["id"]
        if not isinstance(identifier,str) or not identifier or identifier in ids:
            raise ValueError("sound IDs must be distinct")
        ids.add(identifier)
        kind=cue["kind"]
        if kind not in {"contact","friction",*BEDS}:
            raise ValueError("sound kind must be contact, friction, air or water")
        start=resolve(cue,"at",events)
        end=resolve(cue,"until",events) if "until" in cue else (
            min(seconds,start+.28) if start is not None and kind=="contact" else None)
        if start is None or end is None:
            if cue.get("optional") and (start is None or "until" in cue):
                continue
            raise ValueError(f"{identifier}: continuous sounds need an end event")
        if not 0<=start<end<=seconds:
            raise ValueError(f"{identifier}: sound falls outside the timeline")
        lo,hi=round(start*SR),round(end*SR)
        if hi-lo<2:
            raise ValueError(f"{identifier}: sound is too short")
        level=float(cue.get("level",.20))
        distance=float(cue.get("distance",0))
        pan=cue.get("pan",0)
        left,right=pan if isinstance(pan,list) else (pan,pan)
        if not all(map(math.isfinite,(level,distance,left,right))) or not (
            0<=level<=1 and distance>=0 and -1<=left<=1 and -1<=right<=1
        ):
            raise ValueError(f"{identifier}: invalid level, distance or pan")
        signal=effect(cue,lo/SR,hi/SR,zlib.crc32(identifier.encode("utf8")))
        # A smooth distance loss and equal-power movement in the stereo field.
        signal*=level/(1+distance*distance)
        angle=(np.linspace(left,right,len(signal),dtype=np.float32)+1)*(np.pi/4)
        stereo[lo:hi,0]+=signal*np.cos(angle)
        stereo[lo:hi,1]+=signal*np.sin(angle)
        amount=float(cue.get("duck",0))
        if not 0<=amount<=.4:
            raise ValueError(f"{identifier}: duck must be from zero to .4")
        if amount:
            first=max(0,lo-round(.035*SR))
            last=min(count,hi+round(.20*SR))
            t=np.arange(first,last)
            ramp=ease((t-first)/max(1,lo-first))*ease((last-t)/max(1,last-hi))
            np.maximum(duck[first:last],amount*ramp,out=duck[first:last])
        used.append((identifier,start))
    return stereo,duck,used


def read_music(path,count):
    with wave.open(str(path),"rb") as f:
        channels=f.getnchannels()
        if channels not in (1,2) or f.getsampwidth()!=2 or f.getframerate()!=SR:
            raise ValueError("use a 44100 Hz 16-bit WAV, such as the output of score_wav")
        music=np.frombuffer(f.readframes(count),dtype="<i2").reshape(-1,channels).astype(np.float32)/32768
    if len(music)+1<count:
        raise ValueError("music stem is shorter than sound timeline")
    if len(music)<count:
        music=np.pad(music,((0,count-len(music)),(0,0)))
    return music


def write(path,samples):
    peak=float(np.max(np.abs(samples),initial=0))
    pcm=np.asarray(samples*(min(1,.96/max(peak,.0001))*32767),dtype="<i2")
    path.parent.mkdir(parents=True,exist_ok=True)
    with wave.open(str(path),"wb") as f:
        f.setparams((2,2,SR,0,"NONE",""))
        f.writeframes(pcm.tobytes())


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("spec",type=Path)
    parser.add_argument("--music",type=Path)
    parser.add_argument("--out",type=Path,required=True)
    a=parser.parse_args()
    try:
        if a.out.resolve() in (a.spec.resolve(),a.music.resolve() if a.music else None):
            raise ValueError("output needs a separate path")
        doc=json.loads(a.spec.read_text(encoding="utf-8-sig"))
        sound,duck,used=design(doc)
        if a.music:
            sound+=read_music(a.music,len(sound))*(1-duck[:,None])
        write(a.out,sound)
    except (ValueError,TypeError,KeyError,OSError,wave.Error) as exc:
        parser.exit(1,str(exc)[:360]+"\n")
    print(f"{len(used)} aligned sound layers | {len(sound)/SR:.3f}s | {a.out}")


if __name__=="__main__":
    main()
