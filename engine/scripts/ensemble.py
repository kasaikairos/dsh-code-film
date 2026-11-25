"""Small original cue-driven ensemble. All voices are synthesized locally."""
import numpy as np

SR = 44100

def compose(seconds,bpm,seed,mood,cues,arrangement="chamber",pedal=True):
    mix=np.zeros(round(seconds*SR),dtype=np.float32)
    rng=np.random.default_rng(seed)
    beat=60/bpm
    tonic=int(rng.choice([46,48,50,53]))
    def voice(at,length,midi,instrument,level,end_pitch=0):
        start=max(0,round(at*SR))
        n=min(round(length*SR),len(mix)-start)
        if n<2:return
        t=np.arange(n)/SR
        u=t/max(length,0.001)
        freq=440*2**((midi-69+end_pitch*u+.065*np.sin(2*np.pi*4.7*t)*np.minimum(1,3*t))/12)
        phase=(2*np.pi/SR)*np.cumsum(freq)
        partials={"reed":(1,.18,.43,.12,.15),"bow":(1,.49,.27,.17,.12,.08),"horn":(1,.57,.31,.09)}
        attack={"reed":.065,"bow":.24,"horn":.032}[instrument]
        attack = attack * (0.45 if (mech and instrument=="bow") else 1.0)
        env=np.minimum(1,t/min(attack,length*.28))*np.minimum(1,(n/SR-t)/min(.24,length*.38))
        tone=np.zeros(n)
        for k,weight in enumerate(partials[instrument],1):
            tone+=weight*np.sin(k*phase)/(1+.32*k*u)
        mix[start:start+n]+=level*env*(.83+.17*np.sin(np.pi*u))*tone
    # 编曲：mechanical 给“机械连续”的题材一条等距低音脉冲 + 短弓；chamber 是原样
    mech = (arrangement == "mechanical")
    if mech:
        pulse = beat * 0.5
        for at in np.arange(0, seconds, pulse):
            voice(at, min(pulse * 0.82, 0.22), tonic - 24 + (0 if int(at / pulse) % 2 == 0 else 5),
                  "horn", .085, 0)
    # Long pedal and moving inner line; percussion is unnecessary to mark time.
    bar=beat*(3 if mood=="lyric" else 4)
    roots=(0,-5,-2,0) if mood!="suspense" else (0,1,-2,0)
    for i,at in enumerate(np.arange(0,seconds,bar)):
        root=tonic+roots[i%4]
        voice(at,bar*1.04,root-12,"bow",.11) if pedal else None
        voice(at+beat*.25,bar*.88,root+(7 if mood!="suspense" else 6),"bow",.065)
        if mood=="suspense":
            voice(at+beat*.55,bar*.63,root+13,"reed",.092,-1.2)
        elif mood=="playful" and i%2==0:
            voice(at+beat*.24,beat*.83,root+7,"reed",.095,2)
            voice(at+beat*1.55,beat*1.27,root+4,"horn",.085,-2)
        if mood=="lyric":
            voice(at,bar*.68,root+12,"reed",.13)
            voice(at+bar*.65,bar*.39,root+14,"reed",.095)
    events=sorted(cues,key=lambda e:float(e["time"]))
    for i,event in enumerate(events):
        at=float(event["time"]);kind=event["kind"]
        if not 0<=at<seconds:continue
        after=float(events[i+1]["time"]) if i+1<len(events) else seconds
        span=max(.05,min(after-at,beat*3))
        if kind=="soft":
            voice(at,span*.72,tonic+7,"reed",.19,2 if mood=="playful" else .4)
        elif kind=="tick":
            voice(at,span*.66,tonic+10,"reed",.15,-3)
        elif kind=="impact":
            # Prepare the arrival, land once, and let the harmony resolve.
            lead=min(at,beat*.67)
            voice(at-lead,lead,tonic+5,"bow",.12,5)
            voice(at,min(span,.55),tonic,"horn",.25,-1)
            voice(at+.18,min(span,beat*1.6),tonic+7,"bow",.105)
    for event in events:
        if event["kind"]=="breath":
            i=round(float(event["time"])*SR)
            if 0<=i<len(mix):
                sl=mix[max(0,i-round(.12*SR)):min(len(mix),i+round(.15*SR))]
                sl*=1-.96*np.sin(np.linspace(0,np.pi,len(sl)))**2
    if mood=="playful" and events and events[-1]["kind"]=="impact":
        release=float(events[-1]["time"])+min(1.5,beat*2)
        if 0<release<seconds:
            i=round(release*SR)
            tail=mix[i:]
            tail*=np.maximum(0,1-np.arange(len(tail))/(SR*.48))**2
    fade=min(len(mix),round(.28*SR))
    if fade:mix[-fade:]*=np.linspace(1,0,fade)
    return (.8*mix/max(.42,float(np.max(np.abs(mix))))).astype(np.float32)

def compose_light(seconds,bpm,seed,cues):
    """轻巧、可哼的短乐句：没有长低音、没有半音悬停、没有等距敲击。
    结构：走近（两句上行）— 短等（留一个空拍）— 通过（落在一个高音上收住）。"""
    rng=np.random.default_rng(seed)
    mix=np.zeros(round(seconds*SR),dtype=np.float32)
    tonic=int(rng.choice([60,62,64,65]))          # 中音区，贴近人声哼唱
    def pluck(at,length,midi,level):
        start=max(0,round(at*SR)); n=min(round(length*SR),len(mix)-start)
        if n<2:return
        t=np.arange(n)/SR
        freq=440*2**((midi-69)/12)
        ph=2*np.pi*freq*t
        env=np.minimum(1,t/0.008)*np.exp(-t*3.2)
        tone=np.sin(ph)+0.28*np.sin(2*ph)+0.10*np.sin(3*ph)
        mix[start:start+n]+=level*env*tone
    # 五声音阶：0 2 4 7 9（大调五声），怎么排都好哼
    scale=[0,2,4,7,9]
    step=lambda k: tonic+scale[k%5]+12*(k//5)
    at=float(cues[0]["time"]) if cues else seconds*0.5    # cues[0] = 通过那一刻
    lead=max(1.0,at-2.6)
    motif=[0,2,4,3,2]                                        # 上行再回落
    for i,k in enumerate(motif[:4]):                          # 走近：前四音
        pluck(lead+i*(60/bpm)*0.5,len_:=0.42,step(k),.16)
    pluck(at-0.55,0.30,step(3),.12)                           # 短等的最后一个音
    # 通过：同一动机整体升高一级，落点压在事件上
    for i,k in enumerate([1,3,4]):
        pluck(at-0.10+i*(60/bpm)*0.5,0.55,step(k+1),.19)
    pluck(at+0.42,0.9,step(5),.15)
    fade=min(len(mix),round(.25*SR))
    if fade:mix[-fade:]*=np.linspace(1,0,fade)
    return (.8*mix/max(.42,float(np.max(np.abs(mix))))).astype(np.float32)
