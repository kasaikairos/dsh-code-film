"""Compile authored notes into spaced instrumental phrases for score_driver."""
import argparse
import json
import math
from pathlib import Path


VOICE_ALIASES={"reed":"clarinet","bow":"viola","horn":"cello"}
VOICES=("clarinet","viola","cello","flute","violin","bassoon","piano")


def accompany(source, phrases, beat, seconds):
    """Choose a playable path of chord tones beneath the authored foreground."""
    harmony=source.get("harmony",[])
    if not harmony:
        return []
    foreground=[]
    for phrase in phrases:
        if phrase["role"] not in ("lead","response"):
            continue
        start=float(phrase["time"])
        for pitch,length in phrase["notes"]:
            end=start+length*beat
            if pitch is not None:
                foreground.append((start,end,pitch))
            start=end
    ranges={"cello":(36,54,45),"viola":(53,69,59),"bassoon":(36,58,48),
            "piano":(36,69,52)}
    sections={voice:[] for voice in ranges}
    for row in sorted(harmony,key=lambda item:item["time"]):
        start=float(row["time"])
        length=float(row["beats"])
        tones=row["chord"]
        voice=row.get("voice","cello")
        if (voice not in ranges or not math.isfinite(length) or
            not 0<=start<start+length*beat<=seconds+1e-7 or
            not 2<=len(tones)<=5 or any(type(n) is not int or not 0<=n<=11 for n in tones) or
            len(set(tones))!=len(tones)):
            raise ValueError("harmony needs time, beats, 2–5 chord pitch classes and a supporting instrument")
        if sections[voice] and start<sections[voice][-1][0]+sections[voice][-1][1]*beat-1e-7:
            raise ValueError(f"overlapping harmony windows for {voice}")
        sections[voice].append((start,length,tones,row.get("level",.065)))
    output=[]
    for voice,rows in sections.items():
        if not rows:
            continue
        low,high,center=ranges[voice]
        previous={}
        for start,length,tones,_ in rows:
            sounding=[p for a,b,p in foreground if a<start+length*beat and b>start]
            ceiling=min(sounding)-3 if sounding else high
            choices=[p for p in range(low,min(high,ceiling)+1) if p%12 in tones]
            if not choices:
                raise ValueError(f"no {voice} harmony below the foreground at {start:g}s")
            current={}
            for pitch in choices:
                dissonance=sum((p-pitch)%12 in (1,2,6,11) for p in sounding)/max(1,len(sounding))
                local=.10*abs(center-pitch)+1.1*dissonance
                if voice=="cello" and pitch%12!=tones[0]:
                    local+=.85
                if previous:
                    cost,path=min(
                        (cost+.19*abs(pitch-last)+.10*max(0,abs(pitch-last)-5)**2,path)
                        for last,(cost,path) in previous.items())
                else:
                    cost,path=0,()
                current[pitch]=(cost+local,(*path,pitch))
            previous=current
        path=min(previous.values())[1]
        for (start,length,_,level),pitch in zip(rows,path):
            output.append(dict(time=start,role="harmony",voice=voice,
                               notes=[[pitch,.91*length]],level=level))
    return output


def compile_phrases(source):
    bpm=float(source["bpm"])
    seconds=float(source["seconds"])
    if not (20<=bpm<=300 and math.isfinite(seconds) and seconds>0):
        raise ValueError("invalid BPM or duration")
    cues=[]
    occupied={"lead":[],"response":[],"bed":[],"harmony":[]}
    by_voice={voice:[] for voice in VOICES}
    quiet=sorted(source.get("quiet",[]))
    if any(not 0<=a<b<=seconds for a,b in quiet):
        raise ValueError("invalid quiet range")
    scale=60/bpm
    phrases=source["phrases"]
    derived=accompany(source,phrases,scale,seconds)
    for phrase in sorted([*phrases,*derived],key=lambda p:p["time"]):
        role=phrase["role"]
        if role not in occupied:
            raise ValueError("role must be lead, response, bed or harmony")
        start=float(phrase["time"])
        voice=phrase["voice"]
        if voice not in VOICES and voice not in VOICE_ALIASES:
            raise ValueError("use " + ", ".join(VOICES))
        notes=phrase["notes"]
        if not notes or any(not math.isfinite(d) or d<=0 or
            (p is not None and (type(p) is not int or not 0<=p<=127)) for p,d in notes):
            raise ValueError("invalid phrase notes")
        instrument=VOICE_ALIASES.get(voice,voice)
        gain=float(phrase.get("level",{"lead":.20,"response":.13,"bed":.07,"harmony":.065}[role]))
        if not (0<gain<=({"lead":.35,"response":.25,"bed":.12,"harmony":.12}[role])):
            raise ValueError("phrase level exceeds role range")
        pos=start
        for pitch,duration in notes:
            end=pos+duration*scale
            if pitch is not None:
                if any(pos<b-1e-7 and end>a+1e-7 for a,b in quiet):
                    raise ValueError(f"phrase at {start:g}s overlaps a quiet window")
                ranges=(occupied["lead"]+occupied["response"] if role in ("lead","response")
                        else occupied["bed"] if role=="bed" else [])
                if any(pos<b-1e-7 and end>a+1e-7 for a,b in ranges):
                    raise ValueError(f"{role} at {start:g}s overlaps an active voice")
                if any((role=="harmony" or previous=="harmony") and pos<b-1e-7 and end>a+1e-7
                       for a,b,previous in by_voice[instrument]):
                    raise ValueError(f"{instrument} harmony overlaps at {start:g}s")
                by_voice[instrument].append((pos,end,role))
                occupied[role].append((pos,end))
            pos=end
        if start<0 or pos>seconds+1e-7:
            raise ValueError(f"phrase at {start:g}s falls outside film")
        cues.append(dict(kind="phrase",time=start,voice=voice,notes=notes,level=gain))
    if not occupied["lead"]:
        raise ValueError("write at least one foreground phrase")
    return dict(style="ensemble",arrangement="chamber_live",seconds=seconds,bpm=bpm,cues=cues)


def compile_score(source):
    if "sections" not in source:
        return compile_phrases(source)

    seconds=float(source["seconds"])
    sections=source["sections"]
    if not math.isfinite(seconds) or seconds<=0 or not sections:
        raise ValueError("a section score needs a positive duration and at least one section")
    if any(key in source for key in ("phrases","harmony","quiet")):
        raise ValueError("put phrases, harmony and quiet windows inside their sections")
    ids=set()
    cues=[]
    summary=[]
    previous_end=0
    previous_theme=None
    base_bpm=60
    for section in sections:
        name=section["id"]
        start,end=float(section["start"]),float(section["end"])
        if not isinstance(name,str) or not name.strip() or name in ids:
            raise ValueError("section ids must be unique and nonempty")
        if not (abs(start-previous_end)<=1e-7 and start<end<=seconds+1e-7):
            raise ValueError(f"{name}: sections must cover the film in order without gaps or overlaps")
        ids.add(name)
        previous_end=end
        if section.get("silence",False):
            if any(section.get(key) for key in ("phrases","harmony")):
                raise ValueError(f"{name}: a silent section cannot contain music")
            summary.append(dict(id=name,start=start,end=end,voices=[]))
            continue
        try:
            local=compile_phrases({**section,"seconds":end-start,
                                   "bpm":section.get("bpm",source.get("bpm",84))})
        except (ValueError,TypeError,KeyError) as exc:
            raise ValueError(f"{name}: {exc}") from exc
        scale=base_bpm/local["bpm"]
        theme=tuple((VOICE_ALIASES.get(p["voice"],p["voice"]),
                     tuple((note,round(length*scale,6)) for note,length in p["notes"]))
                    for p in section["phrases"] if p["role"] in ("lead","response"))
        if theme==previous_theme and not section.get("reprise",False):
            raise ValueError(f"{name}: foreground repeats the previous cue; revise it or set reprise=true")
        previous_theme=theme
        for cue in local["cues"]:
            notes=[[pitch,length*scale] for pitch,length in cue["notes"]]
            cues.append({**cue,"time":start+cue["time"],"notes":notes})
        voices=sorted({VOICE_ALIASES.get(cue["voice"],cue["voice"]) for cue in local["cues"]
                       if any(note is not None for note,_ in cue["notes"])})
        summary.append(dict(id=name,start=start,end=end,bpm=local["bpm"],voices=voices))
    if abs(previous_end-seconds)>1e-7:
        raise ValueError("sections must end at the film duration")
    return dict(style="ensemble",arrangement="chamber_live",seconds=seconds,bpm=base_bpm,
                cues=cues,sections=summary,explicit_score=True)


def link_board(source,board):
    if board.get("status")!="ready" or not board.get("shots"):
        raise ValueError("use a ready storyboard")
    fps=board["fps"]
    duration=board["frames"]/fps
    if "seconds" in source and abs(source["seconds"]-duration)>1e-7:
        raise ValueError("score duration differs from the storyboard")
    shots=board["shots"]
    cursor=0
    sections=[]
    for section in source["sections"]:
        names=section["shots"]
        if not names or "start" in section or "end" in section:
            raise ValueError("with --board, give each score section its storyboard shot ids")
        selected=shots[cursor:cursor+len(names)]
        if names!=[shot["id"] for shot in selected]:
            raise ValueError(f"{section['id']}: shot ids must follow the selected storyboard in order")
        sections.append({**section,"start":selected[0]["startFrame"]/fps,
                         "end":(selected[-1]["startFrame"]+selected[-1]["frames"])/fps})
        cursor+=len(selected)
    if cursor!=len(shots):
        raise ValueError("score sections must cover every storyboard shot")
    return {**source,"seconds":duration,"sections":sections}


def score_phrases(spec):
    if "sections" not in spec:
        return spec["phrases"]
    return [{**row,"time":float(section["start"])+float(row["time"])}
            for section in spec["sections"] for row in section.get("phrases",[])]


def check_development(phrases):
    """Check one audible thematic return with an intervening contrasting line."""
    lead=[]
    for phrase in sorted(phrases,key=lambda p:p["time"]):
        if phrase["role"]!="lead":
            continue
        notes=[pitch for pitch,_ in phrase["notes"] if pitch is not None]
        if len(notes)<4:
            continue
        intervals=tuple(b-a for a,b in zip(notes,notes[1:]))
        lead.append((float(phrase["time"]),intervals))
    if len(lead)<3:
        raise ValueError("write a lead motif, a contrasting phrase, and a return")
    theme=lead[0][1][:3]
    if not any(theme):
        raise ValueError("the opening motif needs pitched motion")

    def contains_theme(intervals):
        return any(intervals[i:i+len(theme)]==theme for i in range(len(intervals)-len(theme)+1))

    contrast=False
    for time,intervals in lead[1:]:
        if not contains_theme(intervals) and len(set(intervals))>1:
            contrast=True
        elif contrast and contains_theme(intervals):
            return f"motif at {lead[0][0]:g}s, contrasting phrase, return at {time:g}s"
    raise ValueError("develop the lead with contrasting intervals before returning to its motif")


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("spec",type=Path)
    parser.add_argument("--out",required=True,type=Path)
    parser.add_argument("--board",type=Path,help="derive section times from storyboard shot ids")
    parser.add_argument("--developed",action="store_true",
                        help="require a motif, a contrast and a thematic return")
    args=parser.parse_args()
    try:
        spec=json.loads(args.spec.read_text(encoding="utf-8-sig"))
        if args.board:
            spec=link_board(spec,json.loads(args.board.read_text(encoding="utf-8-sig")))
        score=compile_score(spec)
        form=check_development(score_phrases(spec)) if args.developed else ""
        args.out.write_text(json.dumps(score,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
    except (ValueError,TypeError,KeyError,OSError) as exc:
        parser.exit(1,str(exc)[:400]+"\n")
    count=f"{len(score['cues'])} instrumental phrases"
    if "sections" in score:
        count+=f" across {len(score['sections'])} sections"
    print(" | ".join(part for part in (count,form,str(args.out)) if part))


if __name__=="__main__":
    main()
