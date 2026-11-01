"""End-to-end live validation: real ASR -> Muse plan -> real render -> verified download.

Makes exactly one live transcription call and (via the worker) one live director
call, enforced by the ledger (max 2 each). No SAM, no image generation.
"""

from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path

import httpx

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--api", default=os.environ.get("CLIPFORGE_API_URL", "http://localhost:8001"))
parser.add_argument(
    "--audio",
    type=Path,
    default=Path(r"C:\Users\New User\AppData\Local\Temp\opencode\blur-instruction.wav"),
)
parser.add_argument(
    "--clip",
    type=Path,
    default=Path(r"C:\Users\New User\AppData\Local\Temp\opencode\studio-clip.mp4"),
)
parser.add_argument(
    "--out",
    type=Path,
    default=Path(r"C:\Users\New User\AppData\Local\Temp\opencode\live-e2e"),
)
args = parser.parse_args()

API = args.api
AUDIO = args.audio
CLIP = args.clip
OUT = args.out

OUT.mkdir(parents=True, exist_ok=True)
client = httpx.Client(base_url=API, timeout=300.0)

health = client.get("/health").json()
print("HEALTH", health)

with AUDIO.open("rb") as fh:
    r = client.post("/api/transcribe", files={"file": ("instruction.wav", fh, "audio/wav")})
print("TRANSCRIBE", r.status_code)
if r.status_code != 200:
    print(r.text)
    raise SystemExit(1)
tr = r.json()
print(json.dumps({k: tr.get(k) for k in ("text", "language", "session_id", "audio_duration_ms", "provider_name", "is_mock", "transcribe_mode")}, ensure_ascii=False, indent=2))
audio_s = (tr.get("audio_duration_ms") or 0) / 1000.0
print(f"ASR_COST_USD {round(audio_s * 0.18 / 3600, 6)} ({audio_s:.3f}s)")

with CLIP.open("rb") as fh:
    up = client.post("/api/uploads", files={"file": ("clip.mp4", fh, "video/mp4")})
print("UPLOAD", up.status_code)
if up.status_code != 201:
    print(up.text)
    raise SystemExit(1)
job = up.json()
job_id = job["job_id"]
print("JOB", job_id, job["status"], job["stage"])

voice = client.post(
    f"/api/jobs/{job_id}/voice",
    json={"transcript": tr["text"], "transcription_session_id": tr.get("session_id")},
)
print("VOICE", voice.status_code, voice.json().get("ready"))

deadline = time.time() + 420
last = None
while time.time() < deadline:
    body = client.get(f"/api/jobs/{job_id}").json()
    key = (body["status"], body["stage"])
    if key != last:
        print("STATUS", *key)
        last = key
    if body["status"] in ("completed", "failed"):
        break
    time.sleep(2)

final = client.get(f"/api/jobs/{job_id}").json()
print("FINAL", json.dumps({k: final.get(k) for k in ("status", "stage", "attempts", "error")}, ensure_ascii=False, indent=2))

if final["status"] != "completed":
    raise SystemExit(1)

result = client.get(f"/api/jobs/{job_id}/result").json()
plan = result.get("director_plan")
print("DIRECTOR_PLAN", json.dumps({
    "outcome": plan.get("outcome") if plan else None,
    "operations": [o["capability_id"] for o in (plan or {}).get("operations", [])],
    "approval": plan.get("approval_status") if plan else None,
}, ensure_ascii=False, indent=2))
print("DIRECTOR_USAGE", result.get("director_usage"))
print("DIRECTOR_REQUEST_ID", result.get("director_request_id"))
print("RENDER", result.get("rendered"))

dl = client.get(f"/api/jobs/{job_id}/download")
print("DOWNLOAD", dl.status_code, len(dl.content))
if dl.status_code == 200:
    out = OUT / f"{job_id}.mp4"
    out.write_bytes(dl.content)
    print("SAVED", out)
    print("JOB_ID", job_id)
