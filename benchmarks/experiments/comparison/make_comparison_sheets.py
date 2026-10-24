"""Cross-experiment comparison sheets from the standardized renders (identical cameras/lights/settings).

Rows = final models, columns = views. Run:  python make_comparison_sheets.py
"""
import os

from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
ROWS = [
    ("Exp 1  basic procedural", "experiment_01_basic_procedural/renders/basic"),
    ("Exp 2  advanced procedural", "experiment_02_advanced_procedural/renders/advanced"),
    ("Exp 3  sculpting (high-res)", "experiment_03_sculpting/renders/sculpt"),
    ("Exp 4  AI original", "experiment_04_ai_generation/renders/original/ai_original"),
    ("Exp 4  AI repaired", "experiment_04_ai_generation/renders/generated/ai_generated"),
    ("Exp 5  hybrid (game mesh)", "experiment_05_hybrid/renders/hybrid"),
]
SHEETS = {
    "comparison_sheet_main.png": ("Dragon benchmark - all experiments, identical cameras / lights / render settings",
                                  [("02_side_ortho", "side ortho (clay)"), ("03_three_quarter", "three-quarter (material)"),
                                   ("04_head_closeup", "head close-up (material)"), ("08_material", "rear three-quarter (material)")]),
    "comparison_sheet_form.png": ("Form and topology - clay, silhouette, wireframe of the final evaluated mesh",
                                  [("01_front_ortho", "front ortho (clay)"), ("07_clay", "three-quarter (clay)"),
                                   ("06_silhouette", "silhouette (side)"), ("05_wireframe", "wireframe")]),
}
CELL_W, CELL_H, LABEL_W, HEAD_H, TITLE_H = 640, 480, 230, 36, 56

try:
    font = ImageFont.truetype("arial.ttf", 22)
    bold = ImageFont.truetype("arialbd.ttf", 24)
    title_font = ImageFont.truetype("arialbd.ttf", 30)
except OSError:
    font = bold = title_font = ImageFont.load_default()

for name, (title, cols) in SHEETS.items():
    W = LABEL_W + CELL_W * len(cols)
    H = TITLE_H + HEAD_H + CELL_H * len(ROWS)
    sheet = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(sheet)
    d.text((12, 12), title, fill=(20, 20, 20), font=title_font)
    for c, (_, label) in enumerate(cols):
        d.text((LABEL_W + c * CELL_W + 10, TITLE_H + 6), label, fill=(40, 40, 40), font=bold)
    for r, (row_label, prefix) in enumerate(ROWS):
        y = TITLE_H + HEAD_H + r * CELL_H
        words = row_label.split("  ")
        d.text((12, y + CELL_H // 2 - 30), words[0], fill=(20, 20, 20), font=bold)
        d.text((12, y + CELL_H // 2 + 2), words[1] if len(words) > 1 else "", fill=(60, 60, 60), font=font)
        for c, (view, _) in enumerate(cols):
            path = os.path.join(ROOT, f"{prefix}_{view}.png")
            x = LABEL_W + c * CELL_W
            if os.path.isfile(path):
                im = Image.open(path).convert("RGB").resize((CELL_W, CELL_H), Image.LANCZOS)
                sheet.paste(im, (x, y))
            else:
                d.text((x + 20, y + 20), "MISSING " + view, fill=(200, 0, 0), font=font)
            d.rectangle([x, y, x + CELL_W - 1, y + CELL_H - 1], outline=(255, 255, 255), width=2)
    sheet.save(os.path.join(HERE, name))
    print(name, sheet.size)
