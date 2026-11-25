"""Play original chamber scores with CC0 recorded instrument notes."""
from functools import lru_cache
import math
from pathlib import Path
import wave

import numpy as np

SR = 44100
SAMPLES = Path(__file__).resolve().parents[1] / "assets" / "chamber"
ALIASES = {"reed":"clarinet","bow":"viola","horn":"cello"}
PAN = {"clarinet":-.20,"viola":.30,"cello":.07,"flute":-.28,
       "violin":.22,"bassoon":.18,"piano":-.08}


@lru_cache(maxsize=len(PAN))
def bank(instrument):
    notes={}
    for path in sorted(SAMPLES.glob(f"{instrument}-*.wav")):
        with wave.open(str(path),"rb") as sample:
            if sample.getnchannels()!=1 or sample.getsampwidth()!=2:
                raise ValueError(f"invalid instrument sample: {path.name}")
            data=np.frombuffer(sample.readframes(sample.getnframes()),dtype="<i2")
            notes[int(path.stem.split("-")[-1])] = (data.astype(np.float32)/32768,sample.getframerate())
    if not notes:
        raise ValueError(f"missing instrument samples: {instrument}")
    return notes


@lru_cache(maxsize=48)
def find_loop(instrument, root):
    signal,rate=bank(instrument)[root]
    span=int(rate*.065)
    tail=signal[len(signal)-span-2:len(signal)-2]
    tail=tail/max(np.linalg.norm(tail),1e-8)
    # Choose a correlated sustain start near 1.1s instead of resetting phase arbitrarily.
    step=4
    center=min(int(rate*1.10),len(signal)//2)
    radius=int(rate*.025)
    candidates=np.arange(center-radius,center+radius,step)
    windowed=np.lib.stride_tricks.sliding_window_view(signal,span)[candidates]
    similarity=(windowed@tail)/np.maximum(np.linalg.norm(windowed,axis=1),1e-8)
    return int(candidates[np.argmax(similarity)])


def note_wave(instrument, pitch, length, connected):
    notes=bank(instrument)
    root=min(notes,key=lambda n:abs(n-pitch))
    signal,rate=notes[root]
    speed=(rate/SR)*2**((pitch-root)/12)
    if instrument=="piano":
        # Play the recorded decay from its onset without looping the hammer strike.
        return np.interp(speed*np.arange(length),np.arange(len(signal)),signal,right=0)
    first=int(rate*.11) if connected else 0
    indices=first+speed*np.arange(length)
    last=len(signal)-2
    looping=indices>last
    original=indices.copy()
    if looping.any():
        blend=int(rate*.065)
        loop_start=find_loop(instrument,root)
        loop_length=last-loop_start-blend
        indices[looping]=loop_start+blend+(indices[looping]-last)%loop_length
        sample=np.interp(indices,np.arange(len(signal)),signal)
        cross=(indices>last-blend)&(original>loop_start)
        phase=(indices[cross]-(last-blend))/blend
        head=np.interp(loop_start+phase*blend,np.arange(len(signal)),signal)
        fade=.5-.5*np.cos(np.pi*phase)
        sample[cross]=sample[cross]*(1-fade)+head*fade
        return sample
    return np.interp(indices,np.arange(len(signal)),signal)


@lru_cache(maxsize=len(PAN))
def mellow_filter(instrument):
    """Gentle multi-band rolloff, applied after pitch conversion."""
    bands={
        "viola":((1480,.68),(2650,.23),(4300,.09)),
        "cello":((1580,.58),(2900,.30),(4700,.12)),
        "clarinet":((2200,.62),(3300,.28),(5200,.10)),
        "flute":((2400,.55),(3650,.37),(5200,.08)),
        "violin":((1850,.57),(2900,.33),(4500,.10)),
        "bassoon":((1550,.64),(2450,.28),(3800,.08)),
        "piano":((1700,.53),(2750,.34),(4600,.13)),
    }
    offsets=np.arange(-80,81)
    window=np.hanning(len(offsets))
    def lowpass(cutoff):
        fraction=2*cutoff/SR
        taps=fraction*np.sinc(fraction*offsets)*window
        return taps/taps.sum()
    return sum(weight*lowpass(frequency) for frequency,weight in bands[instrument])


def compose(seconds,bpm,cues):
    beat=60/bpm
    mix=np.zeros((round(seconds*SR),2),dtype=np.float32)
    phrases=[cue for cue in cues if cue.get("kind")=="phrase"]
    opening=min((float(cue["time"])+beat*cue.get("offset_beats",0)
                 for cue in phrases if any(pitch is not None for pitch,_ in cue["notes"])),
                default=0)
    opening=max(0,round(opening*SR))
    for cue in phrases:
        instrument=ALIASES.get(cue.get("voice","clarinet"),cue.get("voice","clarinet"))
        if instrument not in PAN:
            raise ValueError(f"unsupported instrument: {instrument}")
        pan=PAN[instrument]
        stereo=np.array([math.sqrt((1-pan)/2),math.sqrt((1+pan)/2)],dtype=np.float32)
        level=float(cue.get("level",.20))
        if not 0<=level<=1:
            raise ValueError("level must be 0–1")
        notes=cue["notes"]
        exact_start=(float(cue["time"])+beat*cue.get("offset_beats",0))*SR
        start=round(exact_start)
        frames=[]
        elapsed=0
        boundary=start
        for pitch,beats in notes:
            if not math.isfinite(beats) or beats<=0 or (pitch is not None and not 0<=pitch<=127):
                raise ValueError("invalid pitch or duration")
            elapsed+=beats*beat*SR
            next_boundary=max(boundary+1,round(exact_start+elapsed))
            frames.append(next_boundary-boundary)
            boundary=next_boundary
        span=sum(frames)
        cursor=start
        for i,((pitch,_),duration) in enumerate(zip(notes,frames)):
            if pitch is None:
                cursor+=duration
                continue
            prior=i>0 and notes[i-1][0] is not None
            following=i+1<len(notes) and notes[i+1][0] is not None
            overlap=min(round(SR*.048),duration//5,frames[i+1]//5) if following else 0
            entry_attack=.19 if cursor<opening+round(.65*SR) else .11
            attack_time=.042 if instrument=="piano" else .040 if prior else entry_attack
            attack=min(round(SR*attack_time),max(1,duration//2))
            release=overlap if overlap else min(round(SR*.18),max(1,duration//3))
            length=duration+overlap
            lo,hi=max(0,cursor),min(len(mix),cursor+length)
            if hi>lo:
                signal=note_wave(instrument,pitch,length,prior)
                kernel=mellow_filter(instrument)
                pad=len(kernel)//2
                signal=np.convolve(np.pad(signal,pad,mode="edge"),kernel,mode="valid")
                t=np.arange(length)
                rise=np.clip(t/attack,0,1)
                fall=np.clip((length-1-t)/release,0,1)
                env=(.5-.5*np.cos(np.pi*rise))*(.5-.5*np.cos(np.pi*fall))
                # Phrase-level shaping is shared across notes, including held accompaniment.
                phrase_time=np.clip((cursor-start+t)/span,0,1)
                shape=.70+.30*np.sin(np.pi*phrase_time)
                mix[lo:hi]+=(signal*env*shape*level)[lo-cursor:hi-cursor,None]*stereo
            cursor+=duration
    # Ease in the whole opening, including explicit scores with a chord at t=0.
    entry=min(round(.22*SR),len(mix)-opening)
    if entry>1:
        phase=np.linspace(0,np.pi,entry,dtype=np.float32)
        mix[opening:opening+entry]*=(.5-.5*np.cos(phase))[:,None]
    fade=min(len(mix),round(.24*SR))
    if fade:
        mix[-fade:]*=np.linspace(1,0,fade,dtype=np.float32)[:,None]
    peak=max(.001,float(np.max(np.abs(mix),initial=0)))
    return mix*min(2.8,.77/peak)


def original_score(seconds,bpm,seed,mood):
    """Write a theme, a contrast and a return for an instrumental trio."""
    rng=np.random.default_rng(seed)
    tonic=int(rng.choice([60,62,63,65]))
    scale=(0,2,3,5,7,8,10) if mood=="suspense" else (0,2,4,5,7,9,11)

    def pitch(degree):
        return tonic+scale[degree%7]+12*(degree//7)

    beat=60/bpm
    lift=int(rng.choice([2,3]))
    phrases=(
        ((0,1.5),(lift,.75),(4,1.25),(2,1.5),(None,.5),(1,.75),(0,1.25)),
        ((0,1.5),(lift,.75),(4,1.25),(5,1.75),(None,.5),(3,.75),(2,1.0)),
        ((4,1),(5,.75),(7,1.5),(6,.75),(5,1.5),(None,.65),(3,1.35)),
        ((4,1.15),(3,.85),(2,1.45),(1,.8),(None,.5),(0,2.65)),
    )
    # Two chord roots and their bass voicings per phrase.
    harmony=((0,-14,4,-10),(3,-11,0,-14),(5,-9,3,-11),(4,-10,0,-14))
    result=[]

    def add(voice,t,level,notes):
        if t+.16<seconds:
            result.append(dict(kind="phrase",time=float(t),voice=voice,level=level,
                notes=[[None if n is None else pitch(n),length] for n,length in notes]))

    for i,t in enumerate(np.arange(.17,max(.17001,seconds-.66),beat*8)):
        form=i%4
        lead="viola" if form==2 else "clarinet"
        answer="clarinet" if lead=="viola" else "viola"
        melody=phrases[form]
        a,b,c,d=harmony[form]
        add(lead,t,.32 if form!=2 else .29,melody)
        if i==0:
            # Let the leading phrase establish its timbre before the first bow.
            add("cello",t+beat*1.7,.20,((b,2.35),(d,2.8)))
            continue
        add("cello",t+beat*.18,.22,((b,3.7),(d,2.9)))
        if form==2:
            add(answer,t+beat*4.3,.17,((c+2,1.35),(c,1.3)))
        elif form==3:
            add(answer,t+beat*1.25,.16,((a-5,2.3),(c-3,1.1),(c-5,2.3)))
        else:
            add(answer,t+beat*3.25,.17,((a-5,1.6),(c-3,1.1),(c-5,1.7)))
    return result
