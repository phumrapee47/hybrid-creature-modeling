"""Find realistic 3D models made by other people to use as reference (step 0 of the pipeline).

Usage (plain Python, no Blender, no account, no downloads):
  python reference_search.py --out <dir> --kind artist --query dragon wyvern
  python reference_search.py --out <dir> --kind real   --query "komodo dragon" crocodile alligator iguana

Searches the public Sketchfab API (anonymous, read-only metadata) and writes
  <out>/reference_candidates_<kind>.json  candidates with url, author, licence, likes, face count, thumbnail url
  <out>/reference_candidates_<kind>.html  contact sheet that hot-links the thumbnails (open it in a browser to look)

kind = artist : creatures category, high poly (sculpts), stylised/low-poly/fan-game noise filtered out
kind = real   : scans and anatomy of real animals (museum scans, photogrammetry, CT), any category

Nothing is downloaded: the thumbnails load only when the sheet is viewed. Downloading a model file needs the
user's permission, and on Sketchfab their own login; record what you use in references.json (SKILL.md step 0).
Ranking is popularity and polycount only: realism and anatomy are judged by looking, never by this score.
"""
import argparse
import html
import json
import os
import urllib.parse
import urllib.request

API = "https://api.sketchfab.com/v3/search"
STYLISED = {"lowpoly", "low-poly", "low_poly", "cartoon", "chibi", "stylized", "stylised", "toon", "cute", "anime",
            "minecraft", "voxel", "kawaii", "funko", "pokemon", "game-asset-pack", "nsfw"}
REAL_HINTS = {"scan", "photogrammetry", "3dscan", "3d-scan", "museum", "ct", "microct", "micro-ct", "specimen",
              "anatomy", "skull", "skeleton", "taxidermy", "natural-history", "zoology", "herpetology"}

ap = argparse.ArgumentParser()
ap.add_argument("--out", required=True)
ap.add_argument("--kind", choices=("artist", "real"), default="artist")
ap.add_argument("--query", nargs="+", required=True)
ap.add_argument("--count", type=int, default=24, help="results per query (API maximum 24)")
ap.add_argument("--min-faces", type=int, default=None, help="default: 150k for artist sculpts, 100k for scans")
ap.add_argument("--keep", type=int, default=30, help="candidates written to the sheet")
args = ap.parse_args()


def search(q):
    p = {"type": "models", "q": q, "sort_by": "-likeCount", "count": min(args.count, 24),
         "min_face_count": args.min_faces or (150000 if args.kind == "artist" else 100000)}
    if args.kind == "artist":
        p["categories"] = "characters-creatures"
    req = urllib.request.Request(API + "?" + urllib.parse.urlencode(p), headers={"User-Agent": "creature-reference-search"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r).get("results", [])


def thumb(r, width=480):
    imgs = sorted((r.get("thumbnails") or {}).get("images", []), key=lambda i: abs(i.get("width", 0) - width))
    return imgs[0]["url"] if imgs else ""


cands, seen = [], set()
for q in args.query:
    for r in search(q):
        if r["uid"] in seen:
            continue
        seen.add(r["uid"])
        tags = {t["slug"] for t in r.get("tags", [])}
        words = set(r["name"].lower().replace("-", " ").split())
        if tags & STYLISED or words & STYLISED or r.get("isAgeRestricted"):
            continue
        real = bool(tags & REAL_HINTS or words & REAL_HINTS)
        lic = (r.get("license") or {}).get("label") or "Store / unknown (view only)"
        cands.append({
            "name": r["name"], "author": r["user"]["username"], "url": r["viewerUrl"], "uid": r["uid"],
            "license": lic, "downloadable": r["isDownloadable"], "staff_pick": bool(r["staffpickedAt"]),
            "likes": r["likeCount"], "views": r["viewCount"], "faces": r["faceCount"], "real_hint": real,
            "tags": sorted(tags)[:15], "query": q, "thumbnail": thumb(r),
            # rank: popularity (log), staff pick, polycount up to ~2M; scans get a boost in kind=real
            "rank": round(__import__("math").log10(1 + r["likeCount"]) + (0.5 if r["staffpickedAt"] else 0)
                          + min(r["faceCount"], 2_000_000) / 2_000_000 + (1.0 if args.kind == "real" and real else 0), 3)})
cands.sort(key=lambda c: -c["rank"])
cands = cands[:args.keep]

os.makedirs(args.out, exist_ok=True)
base = os.path.join(args.out, f"reference_candidates_{args.kind}")
json.dump({"source": API, "kind": args.kind, "queries": args.query, "candidates": cands},
          open(base + ".json", "w", encoding="utf-8"), indent=1, ensure_ascii=False)
cards = "\n".join(
    f'<a class="c" href="{html.escape(c["url"])}"><img src="{html.escape(c["thumbnail"])}" loading="lazy">'
    f'<b>{i + 1}. {html.escape(c["name"][:48])}</b><span>{html.escape(c["author"])} · {c["faces"] / 1e6:.2f}M faces · '
    f'{c["likes"]} likes{" · staff pick" if c["staff_pick"] else ""}</span><span>{html.escape(c["license"])}'
    f'{" · downloadable" if c["downloadable"] else ""}</span></a>' for i, c in enumerate(cands))
open(base + ".html", "w", encoding="utf-8").write(
    "<!doctype html><meta charset=utf-8><title>Reference candidates</title><style>"
    "body{font:13px system-ui;margin:16px;background:#f4f4f2;color:#222}.g{display:grid;"
    "grid-template-columns:repeat(auto-fill,minmax(240px,1fr));gap:10px}.c{background:#fff;border-radius:6px;"
    "padding:6px;text-decoration:none;color:inherit;display:flex;flex-direction:column;gap:2px}"
    ".c img{width:100%;aspect-ratio:16/9;object-fit:cover;border-radius:4px;background:#ddd}span{color:#666}"
    f"</style><h3>Reference candidates ({args.kind}): {html.escape(', '.join(args.query))}</h3>"
    f'<div class="g">{cards}</div>')
print(f"[ref] {len(cands)} candidates -> {base}.json / .html")
for i, c in enumerate(cands[:12]):
    print(f"  {i + 1:2d}. {c['name'][:40]:40s} {c['author'][:18]:18s} {c['faces'] / 1e6:5.2f}M {c['likes']:5d} likes  {c['license']}")
