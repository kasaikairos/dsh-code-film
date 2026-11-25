"""Render two timed stills per space/HTML shot into one compact review sheet."""
import argparse
import json
import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw
from render_spec import ROOT as RUNTIME, scene_page

ROOT = Path(__file__).resolve().parents[1]


def select_shots(shots, budget):
    """Greedily cover the most as-yet-unchecked failure mechanisms."""
    remaining = {i: set(shot.get("review_risks") or [f"unassessed:{i}"])
                 for i, shot in enumerate(shots, 1)}
    chosen, covered = [], set()
    while remaining and len(chosen) < budget:
        index = max(remaining, key=lambda i: len(remaining[i] - covered))
        if not remaining[index] - covered:
            break
        covered.update(remaining.pop(index))
        chosen.append(index)
    return sorted(chosen)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--html-viewport", default="3840x2160",
                        help="match the viewport of custom HTML final shots")
    parser.add_argument("--shots", type=int, nargs="+", help="1-based shot numbers to review")
    parser.add_argument("--budget", type=int, help="maximum shots for a diagnostic sheet")
    args = parser.parse_args()
    if args.budget is not None and (args.budget < 1 or args.shots):
        parser.error("--budget requires a positive integer and excludes --shots")
    shots = json.loads(args.plan.read_text(encoding="utf-8-sig"))["shots"]
    if not shots:
        parser.error("empty shot list")
    chosen = args.shots or list(range(1,len(shots)+1))
    if args.budget:
        chosen = select_shots(shots, args.budget)
    if any(i < 1 or i > len(shots) for i in chosen):
        parser.error("shot number outside plan")
    sheet = Image.new("RGB", (640, len(chosen) * 204))
    labels = ImageDraw.Draw(sheet)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp, args.out.with_suffix(".log").open("w", encoding="utf8") as log:
        for row, number in enumerate(chosen):
            shot = shots[number-1]
            source = (args.plan.parent / shot["source"]).resolve()
            page = source
            viewport = args.html_viewport
            if source.suffix.lower() != ".html":
                spec = json.loads(source.read_text(encoding="utf-8-sig"))
                spec["duration"] = float(shot["seconds"])
                content, viewport = scene_page(spec, source, 640, 360)
                with tempfile.NamedTemporaryFile(mode="w", encoding="utf8", dir=RUNTIME,
                                                 suffix=".html", delete=False) as file:
                    file.write(content)
                    page = Path(file.name)
            times = [float(shot["seconds"]) * fraction for fraction in (0.25, 0.75)]
            folder = Path(tmp) / str(row)
            try:
                subprocess.run(["node", ROOT / "tools/still.mjs", page, "--size", viewport,
                                "--times", ",".join(map(str, times)), "--outdir", folder],
                               check=True, stdout=log, stderr=subprocess.STDOUT)
            finally:
                if page != source:
                    page.unlink(missing_ok=True)
            for col, t in enumerate(times):
                filename = "t" + f"{t:.2f}".replace(".", "_") + ".png"
                # JS and Python may differ when rounding an exact half centisecond.
                images = sorted(folder.glob("*.png"), key=lambda p: float(p.stem[1:].replace("_", ".")))
                image_path = folder / filename
                if not image_path.exists():
                    image_path = images[min(col, len(images)-1)]
                with Image.open(image_path) as image:
                    sheet.paste(image.resize((320, 180), Image.Resampling.LANCZOS), (col*320, row*204))
                labels.text((col*320+5, row*204+181), f"shot {number}   {t:.2f}s")
    sheet.save(args.out)
    print(f"{len(chosen)} shots | {args.out}")


if __name__ == "__main__":
    main()
