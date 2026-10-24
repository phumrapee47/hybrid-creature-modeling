"""Build a labelled contact sheet from rendered views (system Python + Pillow).

Usage:
  python make_contact_sheet.py --dir <renders> --prefix <name> --out <sheet.png> --title "..."
  python make_contact_sheet.py --images a.png b.png --labels A B --cols 2 --out sheet.png
"""
import argparse
import json
import os

from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))

ap = argparse.ArgumentParser()
ap.add_argument("--dir")
ap.add_argument("--prefix")
ap.add_argument("--images", nargs="*")
ap.add_argument("--labels", nargs="*")
ap.add_argument("--cols", type=int, default=4)
ap.add_argument("--cell", type=int, nargs=2, default=[800, 600])
ap.add_argument("--title", default="")
ap.add_argument("--out", required=True)
args = ap.parse_args()

if args.images:
    images, labels = args.images, args.labels or [os.path.basename(p) for p in args.images]
else:
    with open(os.path.join(HERE, "benchmark_settings.json"), encoding="utf-8") as fh:
        views = json.load(fh)["views"]
    images = [os.path.join(args.dir, f"{args.prefix}_{v['id']}.png") for v in views]
    labels = [f"{v['id']}  ({v['shading']})" for v in views]

try:
    font = ImageFont.truetype("arial.ttf", 22)
    tfont = ImageFont.truetype("arialbd.ttf", 30)
except OSError:
    font = tfont = ImageFont.load_default()

cw, ch = args.cell
lab_h, title_h = 34, (50 if args.title else 0)
rows = (len(images) + args.cols - 1) // args.cols
sheet = Image.new("RGB", (cw * args.cols, title_h + rows * (ch + lab_h)), (255, 255, 255))
draw = ImageDraw.Draw(sheet)
if args.title:
    draw.text((12, 10), args.title, fill=(20, 20, 20), font=tfont)
for i, (p, lab) in enumerate(zip(images, labels)):
    x, y = (i % args.cols) * cw, title_h + (i // args.cols) * (ch + lab_h)
    if os.path.isfile(p):
        im = Image.open(p).convert("RGB")
        im.thumbnail((cw, ch))
        sheet.paste(im, (x + (cw - im.width) // 2, y + lab_h))
    else:
        draw.text((x + 12, y + lab_h + 12), "MISSING", fill=(200, 0, 0), font=font)
    draw.text((x + 8, y + 6), lab, fill=(20, 20, 20), font=font)
sheet.save(args.out)
print("sheet:", args.out, sheet.size)
