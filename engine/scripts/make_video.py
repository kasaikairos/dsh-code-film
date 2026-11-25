"""Render, score and mux one scene. Full subprocess output stays on disk."""
import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
SIZES = {"draft":(1280,720), "hd":(1920,1080), "qhd":(2560,1440), "uhd":(3840,2160)}

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--spec",required=True,type=Path)
    ap.add_argument("--out",required=True,type=Path)
    ap.add_argument("--seconds",type=float,default=0)
    ap.add_argument("--fps",type=int,default=None)
    ap.add_argument("--preset",choices=SIZES,default=None)
    ap.add_argument("--outres",default="")
    ap.add_argument("--dpr",type=float)
    ap.add_argument("--gpu",choices=["auto","on","off"],default="auto")
    ap.add_argument("--workers",type=int,default=1)
    ap.add_argument("--intent")
    ap.add_argument("--story")
    ap.add_argument("--picture",type=Path,help="复用已有 MP4 的画面，仅更换音乐")
    for flag in ("no-music","no-check","contact"):
        ap.add_argument("--"+flag,action="store_true")
    ap.add_argument("--soundtrack",type=Path,help="已定稿的全片声轨")
    ap.add_argument("--report", type=Path, help="write a compact quality summary as JSON")
    a=ap.parse_args()
    spec=json.loads(a.spec.read_text(encoding="utf-8-sig"))
    original = {}
    if a.picture:
        original = json.loads(subprocess.check_output(["ffprobe","-v","error","-select_streams","v:0",
            "-show_entries","stream=width,height,duration,avg_frame_rate","-of","json",str(a.picture)]))["streams"][0]
        if not a.outres and not a.preset:
            a.outres = f"{original['width']}:{original['height']}"
        if a.fps is None:
            from fractions import Fraction
            a.fps = float(Fraction(original["avg_frame_rate"]))
    a.fps = 30 if a.fps is None else a.fps
    a.preset = a.preset or "hd"
    seconds=a.seconds or float(spec.get("duration",original.get("duration",8)))
    frames=round(seconds*a.fps)
    if a.fps<=0 or frames<1: ap.error("时长和帧率必须足够生成至少一帧")
    a.out.parent.mkdir(parents=True,exist_ok=True)
    logpath=a.out.with_suffix(".log.txt")
    start=time.perf_counter()
    with tempfile.TemporaryDirectory(dir=a.out.parent) as tmp, logpath.open("w",encoding="utf8") as log:
        def run(args,required=True):
            cmd=list(map(str,args))
            print("$",*cmd,file=log,flush=True)
            result=subprocess.run(cmd,stdout=log,stderr=subprocess.STDOUT,env={**os.environ,"PYTHONUTF8":"1"})
            if required and result.returncode:
                raise RuntimeError(f"{Path(cmd[1] if cmd[0]==sys.executable else cmd[0]).name} 失败，详见 {logpath}")
            return result.returncode
        def script(name,*args,required=True):
            return run([sys.executable,HERE/(name+".py"),*args],required)
        for name,value in (("intent",a.intent),("story",a.story)):
            if value: script(name,"--check",value)
        picture=Path(tmp)/"picture.mp4"
        width,height=map(int,a.outres.split(":")) if a.outres else SIZES[a.preset]
        common=["--spec",a.spec,"--out",picture,"--preset",a.preset,"--fps",a.fps,
                "--outres",f"{width}:{height}","--gpu",a.gpu,"--dpr",a.dpr or max(width/1920,height/1080)]
        if a.picture:
            picture=a.picture
        elif a.workers>1 and frames>60:
            script("render_chunks",*common,"--seconds",seconds,"--workers",a.workers)
        else:
            script("render_spec",*common,"--frames",frames,"--quiet")
        render_time=time.perf_counter()-start
        probe = ["ffprobe", "-v", "error", "-select_streams", "v:0"]
        fields = ["-show_entries", "stream=width,height,nb_frames,avg_frame_rate", "-of", "json"]
        stream = json.loads(subprocess.check_output(probe + fields + [str(picture)]))["streams"][0]
        try:
            nbf = int(stream["nb_frames"])
        except (KeyError, TypeError, ValueError):
            counted = subprocess.check_output(probe + ["-count_frames", "-show_entries",
                "stream=nb_read_frames", "-of", "csv=p=0", str(picture)])
            nbf = int(counted.strip())
        from fractions import Fraction
        fps_ok = abs(float(Fraction(stream["avg_frame_rate"])) - a.fps) <= 0.02
        if ((stream["width"],stream["height"])!=(width,height)
            or not fps_ok
            or (nbf is not None and abs(nbf-frames)>2)):
            raise ValueError(f"画面的尺寸/帧数/帧率与请求不符（实际 {stream['width']}x{stream['height']} "
                             f"{nbf} 帧 {stream['avg_frame_rate']}，要求 {width}x{height} {frames} 帧 {a.fps}）")
        # concat 后帧数可能多 1–2 帧：出片时裁到精确帧数，不让时长偷偷变长
        trim = ["-frames:v", str(frames)] if (nbf is not None and nbf > frames) else []
        output=Path(tmp)/"final.mp4"
        cmd=["ffmpeg","-v","error","-y","-i",picture]
        music_status="无声"
        if a.soundtrack and not a.no_music:
            audio_stream = json.loads(subprocess.check_output(["ffprobe","-v","error","-select_streams","a:0",
                "-show_entries","stream=duration:format=duration","-of","json",str(a.soundtrack)]))
            if not audio_stream["streams"]:
                raise ValueError("soundtrack has no audio")
            audio_duration = float(audio_stream["streams"][0].get("duration") or audio_stream["format"]["duration"])
            if audio_duration + 1/a.fps < frames/a.fps:
                raise ValueError("soundtrack shorter than picture")
            cmd += ["-i",a.soundtrack,"-map","0:v:0","-map","1:a:0","-c:a","aac","-b:a","192k","-t",str(frames/a.fps)]
            music_status = "使用完成声轨"
        elif not a.no_music:
            score=spec.get("music",{})
            style=score.get("style","ensemble")
            cues=score.get("cues",[])
            mood=score.get("mood","playful" if any(c.get("kind")=="impact" for c in cues) else "lyric")
            tempo=score.get("bpm",{"pulse":108,"tide":68,"classic":84,"ensemble":
                      {"lyric":68,"playful":92,"suspense":76}[mood],"none":80}[style])
            wav=Path(tmp)/"score.wav"
            if style=="none":
                # 没有配乐：先铺一条等长静音，让后面的 sfx 混音有底
                subprocess.run(["ffmpeg","-v","error","-y","-f","lavfi","-i",
                                f"anullsrc=r=44100:cl=stereo","-t",str(frames/a.fps),str(wav)],check=True)
                music_status="无配乐"
            else:
                cue_file=Path(tmp)/"music-cues.json"
                cue_file.write_text(json.dumps({"cues":cues,"explicit_score":score.get("explicit_score",False)}),
                                    encoding="utf8")
                script("music_score","--seconds",frames/a.fps,"--style",style,"--mood",mood,"--bpm",tempo,
                   "--seed",score.get("seed",spec.get("seed",7)),"--cues-file",cue_file,
                   "--arrangement",score.get("arrangement","chamber_live"),
                   *(["--no-pedal"] if score.get("no_pedal") else []),
                   "--out",wav,*(["--story",a.story] if a.story else []))
                music_status=style
            # 留白（silent_after）与现场声（sfx）都是编曲的一部分：先合成音乐，再叠环境/音效
            silent_after=score.get("silent_after")
            sfx_spec=score.get("sfx")
            if silent_after is not None or sfx_spec or score.get("shot_sfx"):
                import numpy as _np, wave as _wave
                def _read(pth):
                    with _wave.open(str(pth),"rb") as w:
                        ch=w.getnchannels(); sr=w.getframerate()
                        raw=_np.frombuffer(w.readframes(w.getnframes()),_np.int16).astype(_np.float32)/32768.0
                    return (raw.reshape(-1,ch) if ch>1 else raw.reshape(-1,1)), sr
                mus,sr=_read(wav)
                n=min(len(mus),round(frames/a.fps*sr))
                mus=mus[:n]
                if silent_after is not None:
                    i0=max(0,int(float(silent_after)*sr)); fade=int(0.35*sr)
                    if i0<len(mus):
                        env=_np.ones(len(mus),_np.float32)
                        env[i0:i0+fade]=_np.linspace(1,0,len(env[i0:i0+fade]))
                        env[i0+fade:]=0.0
                        mus=mus*env[:,None]
                if sfx_spec:
                    sspec=Path(tmp)/"sfx.json"; sspec.write_text(json.dumps(sfx_spec),encoding="utf8")
                    swav=Path(tmp)/"sfx.wav"
                    script("sfx","--spec",sspec,"--seconds",frames/a.fps,"--out",swav)
                    sfx,_=_read(swav)
                    m=min(len(sfx),len(mus))
                    gain=float(score.get("sfx_level",1.0))
                    mus=mus[:m]+sfx[:m]*gain
                    music_status+="+sfx"
                if score.get("shot_sfx"):
                    import sfx
                    for segment in score["shot_sfx"]:
                        start_sample = round(segment["start_frame"] * sr / a.fps)
                        samples = sfx.build(segment["sfx"], segment["frames"] / a.fps)
                        count = min(len(samples), len(mus) - start_sample)
                        if count <= 0:
                            continue
                        signal = samples[:count] * float(segment["gain"])
                        mus[start_sample:start_sample + count, 0] += signal
                        if count > 8:
                            mus[start_sample + 8:start_sample + count, 1] += signal[:-8]
                    music_status += "+镜内现场声"
                outwav=Path(tmp)/"mix.wav"
                peak=float(_np.max(_np.abs(mus))) or 1.0
                if peak>0.98: mus=mus*(0.98/peak)
                with _wave.open(str(outwav),"wb") as w:
                    w.setnchannels(mus.shape[1] if mus.ndim>1 else 1); w.setsampwidth(2); w.setframerate(sr)
                    w.writeframes((_np.clip(mus,-1,1)*32767).astype(_np.int16).tobytes())
                wav=outwav
            if style != "none" and not a.no_check and script("music_check","--wav",wav,required=False):
                music_status+="（有配乐指标需复听）"
            cmd+=["-i",wav,"-map","0:v:0","-map","1:a:0","-c:a","aac","-b:a","192k","-t",str(frames/a.fps)]
        else:
            cmd+=["-map","0:v:0","-an"]
        run(cmd+trim+["-c:v","copy","-movflags","+faststart",output])
        status="未做画质体检"
        if not a.no_check:
            rc=script("checks","--video",output,"--fps",a.fps,"--expect",f"{width}x{height}","--strict",required=False)
            status="画面有指标需复查" if rc else "已执行画面体检，覆盖项见日志"
        if a.contact:
            script("contact_sheet","--video",output,"--out",a.out.with_suffix(".sheet.png"),"--n",6)
        if not a.no_music and not a.soundtrack: os.replace(wav,a.out.with_suffix(".wav"))
        os.replace(output,a.out)
        if a.report:
            a.report.write_text(json.dumps({"picture": status, "music": music_status},
                                           ensure_ascii=False), encoding="utf8")
    print(f"{a.out} | {width}×{height} | {frames}帧 | 画面阶段 {render_time:.2f}s")
    print(f"配乐 {music_status} | {status} | 日志 {logpath}")

if __name__=="__main__":
    try:main()
    except (ValueError,RuntimeError,OSError,subprocess.SubprocessError,KeyError) as error:
        sys.exit(str(error))

