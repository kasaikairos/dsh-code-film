"""Cheap checks on the evidence and on the actual instrumental soundtrack."""
import argparse
import json
import math
from pathlib import Path
import subprocess
from urllib.parse import urlsplit

import numpy as np


def media_metrics(path):
    # Analyze channels independently to avoid cancelling stereo transients.
    rate = 16000
    data = subprocess.check_output([
        "ffmpeg", "-v", "error", "-i", str(path), "-map", "0:a:0",
        "-ac", "2", "-ar", str(rate), "-f", "f32le", "-"
    ])
    audio = np.frombuffer(data, dtype="<f4").reshape(-1, 2)
    window, hop = 512, 160
    if len(audio) < window or not np.isfinite(audio).all():
        raise ValueError("invalid or too short soundtrack")
    frames = np.lib.stride_tricks.sliding_window_view(audio, window, axis=0)[::hop]
    power = (np.abs(np.fft.rfft(frames * np.hanning(window), axis=-1)) ** 2).sum(axis=1)
    high = power[:, 48:].sum(axis=1)  # 1.5 kHz and above
    energy = power.sum(axis=1)
    if energy.max() <= 1e-12:
        raise ValueError("soundtrack contains no measurable signal")
    audible = energy > energy.max() * .001
    ratio = high / np.maximum(energy, 1e-12)
    # Fast upward spectral change, relative to the stronger adjacent frame.
    flux = np.maximum(np.diff(power, axis=0), 0).sum(axis=1)
    flux /= np.maximum(np.maximum(energy[1:], energy[:-1]), 1e-12)
    candidates = np.flatnonzero((flux > .55) & audible[1:] & (ratio[1:] > .55)) + 1
    peaks = []
    for index in candidates:
        if not peaks or index - peaks[-1] >= 8:
            peaks.append(index)
    # Find the densest two-second interval so quiet passages cannot hide a burst.
    left = 0
    peak_count, worst = 0, 0
    for right, index in enumerate(peaks):
        while index - peaks[left] >= 200:
            left += 1
        if right-left+1 > peak_count:
            peak_count, worst = right-left+1, peaks[left]
    duration = len(audio) / rate
    return {"brightAttacksPerSec": peak_count / min(2, duration),
            "brightEnergyShare": float(high.sum() / energy.sum()),
            "worstTime": round(worst * hop / rate, 2)}


def years(value):
    if len(value) != 2 or any(type(y) is not int for y in value) or value[0]>value[1]:
        raise ValueError("use [earliestYear, latestYear], BCE years negative")
    return value


def violations(profile, directory):
    for review in profile.get("reviews", []):
        if not all(str(review.get(k, "")).strip() for k in ("id","observation","evidence")):
            raise ValueError("reviews require id, observation and evidence")
        if review.get("verdict") != "pass":
            yield {"id":review["id"],"issue":"review unresolved","observation":review["observation"]}

    for fact in profile.get("facts", []):
        identifier = fact["id"]
        verdict = fact["verdict"]
        if verdict == "fiction":
            if not str(fact.get("label","")).strip():
                yield {"id":identifier,"issue":"missing visible fiction label"}
            continue
        source = urlsplit(fact.get("source",""))
        if (verdict != "supported" or source.scheme not in ("https","http") or not source.hostname
                or not all(str(fact.get(k,"")).strip() for k in ("claim","evidence"))):
            yield {"id":identifier,"issue":"historical support missing or disputed"}
            continue
        scene_years = years(fact["sceneYears"])
        supported_years = years(fact["supportedYears"])
        if max(scene_years[0],supported_years[0]) > min(scene_years[1],supported_years[1]):
            yield {"id":identifier,"issue":"date ranges do not overlap",
                   "sceneYears":scene_years,"supportedYears":supported_years}

    music = profile.get("music")
    if music is None:
        return
    limits = {"brightAttacksPerSec":music.get("maxBrightAttacksPerSec", 2.5),
              "brightEnergyShare":music.get("maxBrightEnergyShare", .45)}
    if not all(math.isfinite(x) and x>=0 for x in limits.values()) or limits["brightEnergyShare"]>1:
        raise ValueError("invalid music limits")
    metrics = media_metrics(directory / music["file"])
    failed = {name:limit for name,limit in limits.items() if metrics[name]>limit}
    if failed:
        yield {"id":"music","issue":"excessive bright attacks or bright energy",
               "metrics":{k:round(v,4) for k,v in metrics.items()},"limits":failed}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("profile",type=Path)
    args = parser.parse_args()
    try:
        profile = json.loads(args.profile.read_text(encoding="utf-8-sig"))
        failures = list(violations(profile,args.profile.parent))
    except (ValueError,TypeError,KeyError,AttributeError,OSError,subprocess.CalledProcessError) as exc:
        parser.exit(2,"gate input: "+str(exc)[:500]+"\n")
    for failure in failures[:6]:
        print(json.dumps(failure,ensure_ascii=False))
    print(f"{len(failures)} evidence/audio checks failed" if failures else "evidence/audio checks passed")
    return int(bool(failures))


if __name__ == "__main__":
    raise SystemExit(main())
