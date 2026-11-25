"""One render per output; persistent, compact progress independent of the chat."""
import contextlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from uuid import uuid4


def status_file(out):
    return out.with_suffix(out.suffix + ".job.json")


@contextlib.contextmanager
def try_lock(out):
    with open(str(out) + ".lock", "a+b") as lock:
        lock.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            yield False
        else:
            yield True


def update(out, **info):
    path = status_file(out)
    info.update(pid=os.getpid(), output=out.name)
    if token:=os.environ.get("CODEFILM_JOB_TOKEN"):
        info["run"]=token
    with tempfile.NamedTemporaryFile("w", encoding="utf8", dir=out.parent, delete=False) as f:
        json.dump(info, f, ensure_ascii=False)
    os.replace(f.name, path)


def read(out):
    try:
        state = json.loads(status_file(out).read_text(encoding="utf8"))
    except FileNotFoundError:
        return {"state": "not started"}
    if state["state"] == "running":
        with try_lock(out) as free:
            if free:
                state["state"] = "interrupted"
    return state


def start(out):
    with try_lock(out) as free:
        if not free:
            print(status_file(out).read_text(encoding="utf8") if status_file(out).exists() else "starting")
            return
    cmd = [sys.executable, str(Path(sys.argv[0]).resolve()), *[x for x in sys.argv[1:] if x != "--background"]]
    token=uuid4().hex
    opts = {"env":{**os.environ,"CODEFILM_JOB_TOKEN":token}}
    if os.name == "nt":
        opts["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
    else:
        opts["start_new_session"] = True
    with out.with_suffix(".worker.log").open("a", encoding="utf8") as log:
        opts.update(stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, close_fds=True)
        if os.name == "nt":
            try:
                p = subprocess.Popen(cmd, **{**opts, "creationflags":opts["creationflags"] | subprocess.CREATE_BREAKAWAY_FROM_JOB})
            except PermissionError:
                # A managed host may forbid breakaway; keep its isolation policy.
                p = subprocess.Popen(cmd, **opts)
        else:
            p = subprocess.Popen(cmd, **opts)
    for _ in range(50):
        state = read(out)
        if state.get("run")==token or p.poll() is not None:
            break
        time.sleep(0.1)
    if p.poll() not in (None, 0) and state.get("state") != "running":
        raise SystemExit(f"startup failed: {out.with_suffix('.worker.log')}")
    print(json.dumps(state if state.get("run")==token or state.get("state")=="running"
                     else {"state":"starting","pid":p.pid}, ensure_ascii=False))
