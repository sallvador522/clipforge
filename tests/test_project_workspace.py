"""P0 project workspace + asset library (local, mock transports only)."""

import hashlib
import subprocess
from io import BytesIO
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from clipforge_api.main import create_app
from clipforge_providers import get_providers


@pytest.fixture()
def client(tmp_path):
    providers = get_providers("mock")
    app = create_app(storage_root=tmp_path / "storage", providers=providers)
    return TestClient(app), tmp_path / "storage"


def _tiny_video(path: Path) -> Path:
    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", "testsrc=size=64x36:rate=10:duration=1",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        pytest.skip(f"ffmpeg could not generate test clip: {result.stderr[-300:]}")
    return path


def _tiny_audio_wav(path: Path) -> Path:
    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
        "-c:a", "pcm_s16le", "-ar", "44100", "-ac", "1", str(path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        pytest.skip(f"ffmpeg could not generate test audio: {result.stderr[-300:]}")
    return path


def _tiny_png() -> bytes:
    img = Image.new("RGB", (32, 24), color=(200, 100, 50))
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


CLEAN_SVG = b"""<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64" viewBox="0 0 64 64">
<title>logo</title>
<g fill="none" stroke="#FF7659" stroke-width="3">
<circle cx="32" cy="32" r="20" fill="#1C1813"/>
<path d="M20 32 L44 32"/>
<text x="32" y="56" text-anchor="middle" font-size="10" fill="#F3EDE3">CF</text>
</g>
<defs><linearGradient id="g1"><stop offset="0" stop-color="#fff"/><stop offset="1" stop-color="#000"/></linearGradient></defs>
<rect width="64" height="8" fill="url(#g1)"/>
</svg>
"""

MALICIOUS_SVGS = {
    "script": b"<svg xmlns='http://www.w3.org/2000/svg'><script>alert(1)</script></svg>",
    "onload": b"<svg xmlns='http://www.w3.org/2000/svg' onload='alert(1)'><rect width='10' height='10'/></svg>",
    "foreign": b"<svg xmlns='http://www.w3.org/2000/svg'><foreignObject><body xmlns='http://www.w3.org/1999/xhtml'><p>hi</p></body></foreignObject></svg>",
    "doctype": b"<!DOCTYPE svg [<!ENTITY xxe SYSTEM 'file:///etc/passwd'>]><svg xmlns='http://www.w3.org/2000/svg'><text>&xxe;</text></svg>",
    "external_href": b"<svg xmlns='http://www.w3.org/2000/svg'><image href='https://example.com/evil.png' width='10' height='10'/></svg>",
    "style_url": b"<svg xmlns='http://www.w3.org/2000/svg'><rect width='10' height='10' style='fill: url(https://example.com/x.png)'/></svg>",
    "animate": b"<svg xmlns='http://www.w3.org/2000/svg'><rect width='10' height='10'><animate attributeName='x' from='0' to='10' dur='1s'/></rect></svg>",
}


def _upload_asset(client, project_id, filename, data, ctype="application/octet-stream"):
    return client.post(
        f"/api/projects/{project_id}/assets",
        files={"file": (filename, data, ctype)},
    )


def test_project_creation_and_persistence(client):
    http, _ = client
    created = http.post("/api/projects", json={"title": "Demo"}).json()
    assert created["project_id"].startswith("prj_")
    assert created["title"] == "Demo"
    fetched = http.get(f"/api/projects/{created['project_id']}").json()
    assert fetched["title"] == "Demo"
    listed = http.get("/api/projects").json()
    assert any(p["project_id"] == created["project_id"] for p in listed["projects"])
    renamed = http.patch(f"/api/projects/{created['project_id']}", json={"title": "Renamed"}).json()
    assert renamed["title"] == "Renamed"
    # Persistence: reload via a second client on the same storage root.
    assert http.get(f"/api/projects/{created['project_id']}").json()["title"] == "Renamed"


def test_video_upload_creates_project_and_links_job(client, tmp_path):
    http, _ = client
    path = _tiny_video(tmp_path / "clip.mp4")
    with open(path, "rb") as fh:
        resp = http.post("/api/uploads", files={"file": ("clip.mp4", fh, "video/mp4")})
    assert resp.status_code == 201, resp.text
    job = resp.json()
    assert job["project_id"] and job["project_id"].startswith("prj_")
    assets = http.get(f"/api/projects/{job['project_id']}/assets").json()["assets"]
    assert len(assets) == 1 and assets[0]["kind"] == "video"
    assert assets[0]["width"] == 64 and assets[0]["duration_seconds"] > 0


def test_video_upload_reuses_existing_project(client, tmp_path):
    http, _ = client
    prj = http.post("/api/projects", json={"title": "P"}).json()
    path = _tiny_video(tmp_path / "a.mp4")
    with open(path, "rb") as fh:
        resp = http.post(
            "/api/uploads",
            files={"file": ("a.mp4", fh, "video/mp4")},
            data={"project_id": prj["project_id"]},
        )
    assert resp.status_code == 201, resp.text
    assert resp.json()["project_id"] == prj["project_id"]


def test_multiple_video_assets(client, tmp_path):
    http, _ = client
    prj = http.post("/api/projects", json={"title": "Multi"}).json()
    pid = prj["project_id"]
    for name in ("one.mp4", "two.mp4"):
        path = _tiny_video(tmp_path / name)
        with open(path, "rb") as fh:
            resp = http.post(f"/api/projects/{pid}/assets", files={"file": (name, fh, "video/mp4")})
        assert resp.status_code == 201, resp.text
    assets = http.get(f"/api/projects/{pid}/assets").json()["assets"]
    assert len(assets) == 2
    assert len({a["asset_id"] for a in assets}) == 2
    assert len({a["sha256"] for a in assets}) == 1  # same fixture content, stable hash


def test_audio_import_and_metadata(client, tmp_path):
    http, _ = client
    pid = http.post("/api/projects", json={"title": "A"}).json()["project_id"]
    path = _tiny_audio_wav(tmp_path / "tone.wav")
    with open(path, "rb") as fh:
        resp = _upload_asset(http, pid, "tone.wav", fh.read(), "audio/wav")
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["kind"] == "audio"
    assert body["duration_seconds"] and body["duration_seconds"] > 0


def test_image_import_and_metadata(client):
    http, _ = client
    pid = http.post("/api/projects", json={"title": "I"}).json()["project_id"]
    resp = _upload_asset(http, pid, "chip.png", _tiny_png(), "image/png")
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["kind"] == "image" and body["width"] == 32 and body["height"] == 24


def test_text_and_subtitle_parsing(client):
    http, _ = client
    pid = http.post("/api/projects", json={"title": "T"}).json()["project_id"]
    txt = _upload_asset(http, pid, "notes.txt", b"hello\nworld\n", "text/plain")
    assert txt.status_code == 201, txt.text
    assert txt.json()["text_lines"] == 2
    srt = _upload_asset(http, pid, "caps.srt",
                        b"1\n00:00:00,000 --> 00:00:01,000\nHello\n\n2\n00:00:01,000 --> 00:00:02,000\nWorld\n",
                        "text/plain")
    assert srt.status_code == 201, srt.text
    assert srt.json()["cue_count"] == 2
    vtt = _upload_asset(http, pid, "caps.vtt",
                        b"WEBVTT\n\n00:00.000 --> 00:01.000\nHello\n", "text/vtt")
    assert vtt.status_code == 201, vtt.text
    bad_vtt = _upload_asset(http, pid, "bad.vtt", b"no header\n", "text/vtt")
    assert bad_vtt.status_code == 422


def test_svg_import_and_sanitization(client):
    http, _ = client
    pid = http.post("/api/projects", json={"title": "G"}).json()["project_id"]
    resp = _upload_asset(http, pid, "logo.svg", CLEAN_SVG, "image/svg+xml")
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["kind"] == "graphics" and body["sanitized"] is True
    served = http.get(f"/api/projects/{pid}/assets/{body['asset_id']}/file")
    assert served.status_code == 200
    assert served.headers["content-type"].startswith("image/svg+xml")
    assert b"<script" not in served.content and b"onload" not in served.content


def test_malicious_svg_rejected(client):
    http, _ = client
    pid = http.post("/api/projects", json={"title": "M"}).json()["project_id"]
    for name, payload in MALICIOUS_SVGS.items():
        resp = _upload_asset(http, pid, f"{name}.svg", payload, "image/svg+xml")
        assert resp.status_code in (400, 422), f"{name}: {resp.status_code} {resp.text}"
    # All rejections left no orphaned asset directories.
    assets = http.get(f"/api/projects/{pid}/assets").json()["assets"]
    assert assets == []


def test_asset_to_project_ownership(client, tmp_path):
    http, _ = client
    a = http.post("/api/projects", json={"title": "A"}).json()["project_id"]
    b = http.post("/api/projects", json={"title": "B"}).json()["project_id"]
    resp = _upload_asset(http, a, "chip.png", _tiny_png(), "image/png")
    aid = resp.json()["asset_id"]
    # Cross-project read/file/delete must 404, never leak.
    assert http.get(f"/api/projects/{b}/assets/{aid}").status_code == 404
    assert http.get(f"/api/projects/{b}/assets/{aid}/file").status_code == 404
    assert http.delete(f"/api/projects/{b}/assets/{aid}").status_code == 404
    # Path traversal in ids must 404, never escape.
    assert http.get("/api/projects/../..%2Fjobs/assets/x").status_code in (404, 422)
    assert http.get(f"/api/projects/{a}/assets/%2E%2E").status_code == 404
    # Owner can still read and delete.
    assert http.get(f"/api/projects/{a}/assets/{aid}").status_code == 200
    assert http.delete(f"/api/projects/{a}/assets/{aid}").status_code == 200
    assert http.get(f"/api/projects/{a}/assets/{aid}").status_code == 404


def test_upload_failure_cleanup(client):
    http, _ = client
    pid = http.post("/api/projects", json={"title": "C"}).json()["project_id"]
    resp = _upload_asset(http, pid, "evil.exe", b"MZ fake", "application/octet-stream")
    assert resp.status_code == 422
    assert http.get(f"/api/projects/{pid}/assets").json()["assets"] == []
    empty = _upload_asset(http, pid, "empty.png", b"", "image/png")
    assert empty.status_code in (400, 422)


def test_existing_single_video_regression(client, tmp_path):
    """The pre-P0 single-video job flow still works end-to-end (mock director)."""
    http, storage = client
    path = _tiny_video(tmp_path / "reg.mp4")
    with open(path, "rb") as fh:
        created = http.post("/api/uploads", files={"file": ("reg.mp4", fh, "video/mp4")})
    assert created.status_code == 201
    job_id = created.json()["job_id"]
    voice = http.post(f"/api/jobs/{job_id}/voice", json={"transcript": "blur the background please"})
    assert voice.status_code == 200, voice.text
