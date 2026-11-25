"""Run the existing timeline entry in the background with bounded status output."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import time

import render_job


def main():
    parser=argparse.ArgumentParser(description=__doc__,add_help=False,allow_abbrev=False)
    parser.add_argument("launcher",type=Path)
    parser.add_argument("--out",required=True,type=Path)
    mode=parser.add_mutually_exclusive_group()
    mode.add_argument("--background",action="store_true")
    mode.add_argument("--status",action="store_true")
    mode.add_argument("--wait",action="store_true")
    a,options=parser.parse_known_args()
    out=a.out.resolve()
    if a.status or a.wait:
        state=render_job.read(out)
        while a.wait and state["state"]=="running":
            time.sleep(3)
            state=render_job.read(out)
        print(json.dumps(state,ensure_ascii=False))
        return int(a.wait and state["state"]!="complete")
    if not options:
        parser.error("provide the timeline HTML and render settings")
    out.parent.mkdir(parents=True,exist_ok=True)
    if a.background:
        render_job.start(out)
        return 0
    with render_job.try_lock(out) as acquired:
        if not acquired:
            print(json.dumps(render_job.read(out),ensure_ascii=False))
            return 0
        started=time.perf_counter()
        render_job.update(out,state="running",stage="timeline")
        try:
            result=subprocess.call([sys.executable,"-X","utf8",a.launcher,"timeline",*options,
                                    "--out",out])
            if result or not out.is_file():
                raise RuntimeError("timeline failed; see " + out.with_suffix(".worker.log").name)
        except BaseException as error:
            render_job.update(out,state="failed",error=str(error)[-300:])
            raise
        render_job.update(out,state="complete",seconds=round(time.perf_counter()-started,2),
                          bytes=out.stat().st_size)
    return 0


if __name__=="__main__":
    raise SystemExit(main())
