"""Experiment 4, Phase 2 - AI 3D generation with Microsoft TRELLIS (public Hugging Face Space).

Image-to-3D via the Space's public Gradio queue API (standard library only, no account/token):
  start_session -> preprocess_image (background removal + crop) -> generate_and_extract_glb
The returned GLB and preview video are downloaded unmodified into original_asset/ and every
input/setting/timing is appended to generation_attempts.json.

Run:  python generate_trellis.py [reference_image ...]   (one image = single-view; several = multi-image)
"""
import datetime
import json
import mimetypes
import os
import sys
import time
import urllib.request
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
SPACE = "trellis-community/TRELLIS"
HOST = "https://trellis-community-trellis.hf.space"
PREFIX = "/gradio_api"
UA = {"User-Agent": "dragon-benchmark/1.0"}
OUT_DIR = os.path.join(HERE, "original_asset")
LOG = os.path.join(HERE, "generation_attempts.json")
SETTINGS = {"seed": 1234, "ss_guidance_strength": 7.5, "ss_sampling_steps": 12, "slat_guidance_strength": 3.0,
            "slat_sampling_steps": 12, "multiimage_algo": "stochastic", "mesh_simplify": 0.95, "texture_size": 1024}


def http(url, data=None, headers=None, timeout=120):
    req = urllib.request.Request(url, data=data, method="POST" if data is not None else "GET", headers={**UA, **(headers or {})})
    return urllib.request.urlopen(req, timeout=timeout)


def upload(path):
    boundary = uuid.uuid4().hex
    with open(path, "rb") as fh:
        payload = fh.read()
    mime = mimetypes.guess_type(path)[0] or "application/octet-stream"
    body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"files\"; filename=\"{os.path.basename(path)}\"\r\n"
            f"Content-Type: {mime}\r\n\r\n").encode() + payload + f"\r\n--{boundary}--\r\n".encode()
    with http(f"{HOST}{PREFIX}/upload", body, {"Content-Type": f"multipart/form-data; boundary={boundary}"}) as r:
        return {"path": json.load(r)[0], "meta": {"_type": "gradio.FileData"}, "orig_name": os.path.basename(path)}


def run(fn_index, data, session):
    """Join the queue and wait for process_completed; returns (success, output, seconds)."""
    t0 = time.perf_counter()
    body = json.dumps({"data": data, "fn_index": fn_index, "session_hash": session, "event_data": None, "trigger_id": fn_index}).encode()
    http(f"{HOST}{PREFIX}/queue/join", body, {"Content-Type": "application/json"}).read()
    with http(f"{HOST}{PREFIX}/queue/data?session_hash={session}", timeout=1800) as stream:
        for raw in stream:
            line = raw.decode("utf-8", "replace").strip()
            if not line.startswith("data:"):
                continue
            msg = json.loads(line[5:])
            if msg.get("msg") == "process_completed":
                return msg.get("success"), msg.get("output"), round(time.perf_counter() - t0, 1)
            if msg.get("msg") in ("unexpected_error", "queue_full"):
                return False, msg, round(time.perf_counter() - t0, 1)
    return False, "stream closed", round(time.perf_counter() - t0, 1)


def file_url(item):
    if isinstance(item, dict):
        if item.get("url"):
            return item["url"]
        for key in ("value", "video"):
            if isinstance(item.get(key), dict) and item[key].get("url"):
                return item[key]["url"]
    return None


def main(images):
    os.makedirs(OUT_DIR, exist_ok=True)
    session = uuid.uuid4().hex[:11]
    rec = {"tool": f"TRELLIS (Microsoft) via Hugging Face Space {SPACE}", "host": HOST,
           "mode": "image-to-3D, " + ("single image" if len(images) == 1 else f"multi-image ({len(images)})"),
           "text_prompt": None, "input_images": [os.path.relpath(p, HERE) for p in images], "settings": SETTINGS,
           "started_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(), "steps": {}}
    t0 = time.perf_counter()
    rec["steps"]["start_session"] = run(4, [], session)[::2]
    uploaded = [upload(p) for p in images]
    ok, out, sec = run(8, [uploaded[0]], session)  # background removal + crop, as the UI does on upload
    rec["steps"]["preprocess_image"] = {"success": ok, "seconds": sec}
    prompt = out["data"][0] if ok else uploaded[0]
    gallery, multi = [], len(images) > 1
    if multi:  # the UI preprocesses gallery uploads too (fn 9) and sets the is_multiimage state to True
        ok, out, sec = run(9, [[{"image": u, "caption": None} for u in uploaded]], session)
        rec["steps"]["preprocess_images"] = {"success": ok, "seconds": sec}
        gallery = out["data"][0] if ok else [{"image": u, "caption": None} for u in uploaded]
    data = [prompt, gallery, True if multi else None] + list(SETTINGS.values())
    ok, out, sec = run(11, data, session)
    rec["steps"]["generate_and_extract_glb"] = {"success": ok, "seconds": sec}
    rec["total_seconds"] = round(time.perf_counter() - t0, 1)
    if not ok:
        rec["error"] = out
    else:
        rec["downloaded"] = []
        for i, item in enumerate(out["data"]):
            url = file_url(item)
            if url:
                name = f"trellis_output_{i}_{os.path.basename(url.split('?')[0])}"
                with http(url, timeout=600) as r, open(os.path.join(OUT_DIR, name), "wb") as fh:
                    fh.write(r.read())
                rec["downloaded"].append({"file": name, "bytes": os.path.getsize(os.path.join(OUT_DIR, name)), "source_url": url})
    log = json.load(open(LOG, encoding="utf-8")) if os.path.exists(LOG) else []
    log.append(rec)
    with open(LOG, "w", encoding="utf-8") as fh:
        json.dump(log, fh, indent=2, default=str)
    print(json.dumps({k: rec.get(k) for k in ("steps", "total_seconds", "downloaded", "error")}, indent=1, default=str)[:3000])


if __name__ == "__main__":
    main(sys.argv[1:] or [os.path.join(HERE, "reference", "ref_three_quarter.png")])
