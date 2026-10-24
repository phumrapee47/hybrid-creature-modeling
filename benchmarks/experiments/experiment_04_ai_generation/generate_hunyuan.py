"""Experiment 4, Phase 2 - AI 3D generation with Tencent Hunyuan3D-2.1 (public Hugging Face Space).

Image-to-3D: the concept reference image is uploaded to the Space's public Gradio API and the
`/generation_all` endpoint (shape + texture) is called. Outputs are downloaded unmodified into
original_asset/. Every input, setting, timestamp and returned file is recorded in
generation_settings.json. Standard library only (urllib); no Hugging Face account or token.

Run:  python generate_hunyuan.py [reference_image]
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
SPACE = "tencent/Hunyuan3D-2.1"
HOST = "https://tencent-hunyuan3d-2-1.hf.space"
API = "generation_all"
IMAGE = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "reference", "ref_three_quarter.png")
OUT_DIR = os.path.join(HERE, "original_asset")
SETTINGS = {  # endpoint parameters, in API order after the five image slots
    "steps": 30, "guidance_scale": 5.0, "seed": 1234, "octree_resolution": 256,
    "check_box_rembg": True, "num_chunks": 8000, "randomize_seed": False,
}
UA = {"User-Agent": "dragon-benchmark/1.0"}


def upload(path):
    boundary = uuid.uuid4().hex
    with open(path, "rb") as fh:
        payload = fh.read()
    mime = mimetypes.guess_type(path)[0] or "application/octet-stream"
    body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"files\"; filename=\"{os.path.basename(path)}\"\r\n"
            f"Content-Type: {mime}\r\n\r\n").encode() + payload + f"\r\n--{boundary}--\r\n".encode()
    req = urllib.request.Request(f"{HOST}/upload", data=body, method="POST",
                                 headers={**UA, "Content-Type": f"multipart/form-data; boundary={boundary}"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.load(r)[0]


def call(data):
    req = urllib.request.Request(f"{HOST}/call/{API}", data=json.dumps({"data": data}).encode(), method="POST",
                                 headers={**UA, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as r:
        event_id = json.load(r)["event_id"]
    events = []
    with urllib.request.urlopen(urllib.request.Request(f"{HOST}/call/{API}/{event_id}", headers=UA), timeout=1800) as r:
        event = None
        for raw in r:
            line = raw.decode("utf-8", "replace").rstrip("\n")
            if line.startswith("event:"):
                event = line[6:].strip()
            elif line.startswith("data:"):
                events.append((event, line[5:].strip()))
                if event in ("complete", "error"):
                    break
    return event_id, events


def download(url, dest):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=600) as r, open(dest, "wb") as fh:
        fh.write(r.read())
    return os.path.getsize(dest)


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    record = {"tool": f"Hunyuan3D-2.1 (Tencent) via Hugging Face Space {SPACE}", "host": HOST, "endpoint": f"/{API}",
              "mode": "image-to-3D (single image), shape + texture", "text_prompt": None,
              "input_image": os.path.relpath(IMAGE, HERE), "settings": SETTINGS,
              "started_utc": datetime.datetime.now(datetime.timezone.utc).isoformat()}
    t0 = time.perf_counter()
    server_path = upload(IMAGE)
    record["uploaded_as"] = server_path
    file_data = {"path": server_path, "meta": {"_type": "gradio.FileData"}, "orig_name": os.path.basename(IMAGE)}
    data = [file_data, None, None, None, None] + list(SETTINGS.values())
    event_id, events = call(data)
    record["event_id"] = event_id
    record["seconds"] = round(time.perf_counter() - t0, 1)
    final_event, payload = events[-1] if events else (None, None)
    record["final_event"] = final_event
    if final_event != "complete":
        record["error_payload"] = payload
    else:
        result = json.loads(payload)
        record["raw_result"] = result
        saved = []
        for i, item in enumerate(result):
            if isinstance(item, dict) and item.get("url"):
                name = f"hunyuan21_output_{i}_{os.path.basename(item.get('path', 'file'))}"
                size = download(item["url"], os.path.join(OUT_DIR, name))
                saved.append({"file": name, "bytes": size, "source_url": item["url"]})
        record["downloaded"] = saved
    with open(os.path.join(HERE, "generation_settings.json"), "w", encoding="utf-8") as fh:
        json.dump(record, fh, indent=2, default=str)
    print(json.dumps({k: record.get(k) for k in ("final_event", "seconds", "downloaded", "error_payload")}, indent=1)[:3000])


if __name__ == "__main__":
    main()
