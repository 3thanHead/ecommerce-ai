#!/usr/bin/env python3
"""Render the marketing stage's product videos -- ffmpeg, no AI, no cloud.

A "rotating product video" is deterministic media work, so it's code: the
LLM (marketing stage) wrote the hooks/overlays; this renders them over the
product image as a 9:16 clip -- blurred slow-zoom backdrop, the product
gently rotating in front, text beats timed across the clip. Runs the same
on the RTX laptop and the M1 (ffmpeg is everywhere).

    python3 media.py --url http://192.168.1.111:8810 --images ./images
    python3 media.py --file export.json --images ./images --sku <one-sku>
    python3 media.py ... --style spin        # full 360 instead of sway

Inputs:  --images dir with <sku>.png/.jpg -- base images from product
         research (or your own mockups). Missing image = clip skipped.
Output:  videos/<sku>.mp4  (1080x1920, --seconds long, default 12)

Deps: just ffmpeg (`sudo apt install ffmpeg` / `brew install ffmpeg`).
"""
import argparse
import json
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

W, H = 1080, 1920

FONTS = ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",       # linux
         "/System/Library/Fonts/Helvetica.ttc",                       # macOS
         "C:/Windows/Fonts/arialbd.ttf")                              # windows


def find_font() -> str:
    for f in FONTS:
        if Path(f).exists():
            return f
    sys.exit("no usable font found -- pass --font /path/to/font.ttf")


def esc(text: str) -> str:
    """Escape for drawtext: backslash, colon, quote."""
    return (text.replace("\\", "\\\\").replace(":", "\\:")
                .replace("'", "’").replace("%", "\\%"))


def drawtext(font: str, text: str, y: str, start: float, end: float,
             size: int = 64, box: bool = True) -> str:
    common = (f"drawtext=fontfile='{font}':text='{esc(text)}':fontsize={size}:"
              f"fontcolor=white:x=(w-text_w)/2:y={y}:"
              f"enable='between(t,{start},{end})'")
    if box:
        common += ":box=1:boxcolor=black@0.45:boxborderw=18"
    return common


def render(image: Path, out: Path, plan: dict, price: str, seconds: int,
           style: str, font: str) -> None:
    angle = (f"2*PI*t/{seconds}" if style == "spin"
             else f"0.12*sin(2*PI*t/{seconds / 2})")
    texts = [drawtext(font, plan.get("hook", ""), "h*0.12", 0.3, seconds, 72)]
    beats = plan.get("overlay_texts") or []
    if beats:
        window = (seconds - 3) / len(beats)
        for i, beat in enumerate(beats):
            texts.append(drawtext(font, beat, "h*0.72",
                                  round(1.5 + i * window, 2),
                                  round(1.5 + (i + 1) * window, 2), 56))
    texts.append(drawtext(font, f"{plan.get('title', '')} · {price}",
                          "h*0.9", 0, seconds, 44))
    filters = (
        # backdrop: fill the frame, heavy blur, slow zoom
        f"[0:v]scale={W}:{H}:force_original_aspect_ratio=increase,"
        f"crop={W}:{H},boxblur=30:2,"
        f"zoompan=z='1+0.08*on/({seconds}*30)':d={seconds * 30}:s={W}x{H}:fps=30[bg];"
        # product: fit inside, alpha-pad, rotate
        f"[0:v]scale={int(W * 0.82)}:-1:force_original_aspect_ratio=decrease,"
        f"format=rgba,pad=iw+120:ih+120:60:60:color=0x00000000,"
        f"rotate='{angle}':c=none:ow=rotw(iw):oh=roth(ih)[fg];"
        f"[bg][fg]overlay=(W-w)/2:(H-h)/2-100," + ",".join(texts))
    cmd = ["ffmpeg", "-y", "-loop", "1", "-t", str(seconds), "-i", str(image),
           "-filter_complex", filters, "-c:v", "libx264", "-pix_fmt", "yuv420p",
           "-r", "30", "-an", str(out)]
    subprocess.run(cmd, check=True, capture_output=True)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--url")
    src.add_argument("--file")
    ap.add_argument("--images", required=True, help="dir with <sku>.png|.jpg")
    ap.add_argument("--out", default="videos")
    ap.add_argument("--sku", help="render one product only")
    ap.add_argument("--seconds", type=int, default=12)
    ap.add_argument("--style", choices=("sway", "spin"), default="sway")
    ap.add_argument("--font")
    args = ap.parse_args()

    if not shutil.which("ffmpeg"):
        sys.exit("ffmpeg not found -- apt/brew install ffmpeg")
    font = args.font or find_font()
    if args.file:
        export = json.loads(Path(args.file).read_text())
    else:
        with urllib.request.urlopen(f"{args.url.rstrip('/')}/store/export",
                                    timeout=30) as r:
            export = json.load(r)
    plans = (export.get("marketing") or {}).get("plans") or []
    prices = {p["sku"]: p.get("price_usd") for p in export.get("products", [])}
    if args.sku:
        plans = [p for p in plans if p["sku"] == args.sku]
    if not plans:
        sys.exit("no marketing plans in the export -- approve the marketing "
                 "stage first (or bad --sku)")

    outdir = Path(args.out)
    outdir.mkdir(exist_ok=True)
    done = skipped = 0
    for plan in plans:
        image = next((p for ext in ("png", "jpg", "jpeg")
                      for p in [Path(args.images) / f"{plan['sku']}.{ext}"]
                      if p.exists()), None)
        if image is None:
            print(f"skip {plan['sku']}: no image in {args.images}/")
            skipped += 1
            continue
        out = outdir / f"{plan['sku']}.mp4"
        price = f"${prices.get(plan['sku'], '?')}"
        render(image, out, plan, price, args.seconds, args.style, font)
        print(f"rendered {out}")
        done += 1
    print(f"{done} videos, {skipped} skipped")


if __name__ == "__main__":
    main()
