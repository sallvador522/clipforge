"""ADR-047 tests: persisted text overlays, colour grade, render burn-in and tools.

Real execution only: store updates, pixel-level render checks, HTTP API
round-trips and tool validation. No mocks of the units under test.
"""

from __future__ import annotations

import subprocess

import numpy as np
import pytest
from fastapi.testclient import TestClient

from clipforge_api.main import create_app
from clipforge_api.tools import ToolError, execute_tool
from clipforge_contracts import ClipTextOverlay, ColourGrade
from clipforge_jobs import JobStore
from clipforge_providers import get_providers
from clipforge_worker import timeline_render as tr


def _client(tmp_path):
    store = JobStore(tmp_path / "storage")
    providers = get_providers("mock")
    client = TestClient(create_app(storage_root=tmp_path / "storage", providers=providers))
    return client, store


def _upload_clip(client, tmp_path, name="clip.mp4", duration=2):
    path = tmp_path / name
    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", f"testsrc=size=64x36:rate=10:duration={duration}",
        "-f", "lavfi", "-i", f"sine=frequency=440:duration={duration}",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        pytest.skip("ffmpeg could not generate test clip")
    with open(path, "rb") as fh:
        upload = client.post("/api/uploads", files={"file": (name, fh, "video/mp4")})
    assert upload.status_code == 201, upload.text
    return upload.json()["job_id"]


def _overlay(**kw) -> ClipTextOverlay:
    base = {"overlay_id": "txt_test0001", "text": "Hello", "start_s": 0.0, "duration_s": 2.0}
    base.update(kw)
    return ClipTextOverlay.model_validate(base)


def test_overlay_contract_defaults_and_bounds():
    overlay = ClipTextOverlay.model_validate({"overlay_id": "txt_abc123", "text": "Hi"})
    assert overlay.start_s == 0.0 and overlay.duration_s == 2.5
    assert overlay.color == "#FFFFFF" and overlay.weight == "bold"
    with pytest.raises(Exception):
        ClipTextOverlay.model_validate({"overlay_id": "bad id!", "text": "Hi"})
    with pytest.raises(Exception):
        ClipTextOverlay.model_validate({"overlay_id": "txt_x1", "text": ""})
    with pytest.raises(Exception):
        ClipTextOverlay.model_validate(
            {"overlay_id": "txt_x1", "text": "Hi", "color": "red"})


def test_colour_grade_identity_and_ranges():
    assert ColourGrade().is_identity() is True
    assert ColourGrade(contrast=1.2).is_identity() is False
    with pytest.raises(Exception):
        ColourGrade.model_validate({"contrast": 2.0})
    with pytest.raises(Exception):
        ColourGrade.model_validate({"saturation": -1.0})


def test_colour_grade_changes_pixels_in_expected_direction():
    frame = np.full((64, 64, 3), 120, dtype=np.uint8)
    brighter = tr.apply_colour_grade(frame, ColourGrade(brightness=0.1))
    assert float(brighter.mean()) > float(frame.mean()) + 5
    dimmer = tr.apply_colour_grade(frame, ColourGrade(brightness=-0.1))
    assert float(dimmer.mean()) < float(frame.mean()) - 5
    punchier = tr.apply_colour_grade(frame, ColourGrade(contrast=1.5))
    assert float(punchier.std()) >= float(frame.std())
    assert np.array_equal(tr.apply_colour_grade(frame, ColourGrade()), frame)


def test_text_burn_in_appears_only_inside_window():
    overlay = _overlay(text="QA TEXT", x=0.5, y=0.5, scale=1.0)
    blank = np.zeros((tr.CANVAS_H, tr.CANVAS_W, 3), dtype=np.uint8)
    mid = tr.draw_text_overlays(blank.copy(), [overlay], t=1.0)
    assert not np.array_equal(mid, blank)
    assert int((mid > 0).sum()) > 500
    assert np.array_equal(tr.draw_text_overlays(blank.copy(), [overlay], t=5.0), blank)
    assert np.array_equal(tr.draw_text_overlays(blank.copy(), [], t=1.0), blank)


def test_text_colour_is_honoured_in_pixels():
    red = _overlay(overlay_id="txt_red00001", text="RED", color="#FF0000", x=0.5, y=0.5)
    frame = tr.draw_text_overlays(
        np.zeros((tr.CANVAS_H, tr.CANVAS_W, 3), dtype=np.uint8), [red], t=1.0)
    red_mask = (frame[:, :, 2] > 150) & (frame[:, :, 1] < 120) & (frame[:, :, 0] < 120)
    assert int(red_mask.sum()) > 50


def test_texts_api_round_trip(tmp_path):
    client, store = _client(tmp_path)
    job_id = _upload_clip(client, tmp_path)
    payload = {"texts": [
        {"overlay_id": "txt_api00001", "text": "Ola Mundo", "start_s": 0.0,
         "duration_s": 2.0, "x": 0.5, "y": 0.5, "scale": 1.1,
         "color": "#FFD400", "weight": "bold", "style": "rise"},
    ]}
    put = client.put(f"/api/jobs/{job_id}/texts", json=payload)
    assert put.status_code == 200, put.text
    assert put.json()["texts"][0]["text"] == "Ola Mundo"
    # Record really persisted — a fresh read returns the same overlay.
    assert store.get(job_id).clip_texts[0].overlay_id == "txt_api00001"
    got = client.get(f"/api/jobs/{job_id}/texts")
    assert got.status_code == 200 and len(got.json()["texts"]) == 1
    # Invalid colour is rejected, nothing persisted over it.
    bad = client.put(f"/api/jobs/{job_id}/texts", json={"texts": [
        {"overlay_id": "txt_api00002", "text": "X", "color": "red"}]})
    assert bad.status_code == 422
    assert len(store.get(job_id).clip_texts) == 1


def test_colour_api_round_trip(tmp_path):
    client, store = _client(tmp_path)
    job_id = _upload_clip(client, tmp_path)
    put = client.put(f"/api/jobs/{job_id}/colour",
                     json={"contrast": 1.2, "brightness": 0.05, "saturation": 1.3})
    assert put.status_code == 200, put.text
    grade = store.get(job_id).colour
    assert (grade.contrast, grade.brightness, grade.saturation) == (1.2, 0.05, 1.3)
    got = client.get(f"/api/jobs/{job_id}/colour")
    assert got.json()["colour"]["contrast"] == 1.2
    bad = client.put(f"/api/jobs/{job_id}/colour", json={"contrast": 9.0})
    assert bad.status_code == 422


def test_tools_execute_real_project_changes(tmp_path):
    client, store = _client(tmp_path)
    job_id = _upload_clip(client, tmp_path)
    catalogue = client.get(f"/api/jobs/{job_id}/tools")
    assert catalogue.status_code == 200
    names = {t["name"] for t in catalogue.json()["tools"]}
    assert {"text.create", "text.update", "text.delete", "colour.set", "texts.list"} <= names
    created = client.post(f"/api/jobs/{job_id}/tools/execute", json={
        "tool": "text.create",
        "params": {"text": "Muse operou aqui", "start_s": 0.0, "duration_s": 1.5,
                   "x": 0.5, "y": 0.3, "color": "#FFFFFF"}})
    assert created.status_code == 200, created.text
    overlay_id = created.json()["result"]["created"]["overlay_id"]
    updated = client.post(f"/api/jobs/{job_id}/tools/execute", json={
        "tool": "text.update",
        "params": {"overlay_id": overlay_id, "scale": 1.4, "color": "#FFD400"}})
    assert updated.status_code == 200, updated.text
    assert updated.json()["result"]["updated"]["scale"] == 1.4
    record = store.get(job_id)
    assert record.clip_texts[0].color == "#FFD400"
    coloured = client.post(f"/api/jobs/{job_id}/tools/execute", json={
        "tool": "colour.set",
        "params": {"contrast": 1.15, "brightness": 0.0, "saturation": 1.1}})
    assert coloured.status_code == 200, coloured.text
    assert store.get(job_id).colour.contrast == 1.15
    unknown = client.post(f"/api/jobs/{job_id}/tools/execute",
                          json={"tool": "video.fake", "params": {}})
    assert unknown.status_code == 422
    assert unknown.json()["error"]["code"] == "unknown_tool"


def test_tool_validation_rejects_unknown_tool_and_missing_overlay(tmp_path):
    client, store = _client(tmp_path)
    job_id = _upload_clip(client, tmp_path)
    with pytest.raises(ToolError) as exc:
        execute_tool(store, client.app.state.projects, job_id, "nope.not_a_tool", {})
    assert exc.value.code == "unknown_tool"
    with pytest.raises(ToolError) as exc2:
        execute_tool(store, client.app.state.projects, job_id,
                     "text.update", {"overlay_id": "txt_missing"})
    assert exc2.value.code in ("invalid_tool_params", "overlay_not_found")


def test_chat_proposes_real_tool_calls_for_text_edit(tmp_path):
    client, _ = _client(tmp_path)
    job_id = _upload_clip(client, tmp_path)
    put = client.put(f"/api/jobs/{job_id}/texts", json={"texts": [
        {"overlay_id": "txt_chat0001", "text": "Titulo antigo", "start_s": 0.0, "duration_s": 2.0}]})
    assert put.status_code == 200, put.text
    resp = client.post("/api/chat", json={
        "message": "Muda o texto para 'A tua marca aqui'",
        "job_id": job_id, "selected_text_id": "txt_chat0001"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["needs_confirmation"] is True
    calls = body["pending_tool_calls"]
    assert len(calls) == 1 and calls[0]["tool"] == "text.update"
    assert calls[0]["params"]["text"] == "A tua marca aqui"
    # Side-effect free: nothing executed until Executar.
    listed = client.get(f"/api/jobs/{job_id}/texts").json()["texts"]
    assert listed[0]["text"] == "Titulo antigo"
    # Explicit execution applies the real change.
    executed = client.post(f"/api/jobs/{job_id}/tools/execute", json={
        "tool": calls[0]["tool"], "params": calls[0]["params"]})
    assert executed.status_code == 200, executed.text
    listed = client.get(f"/api/jobs/{job_id}/texts").json()["texts"]
    assert listed[0]["text"] == "A tua marca aqui"


def test_chat_asks_clarification_for_ambiguous_target(tmp_path):
    client, _ = _client(tmp_path)
    job_id = _upload_clip(client, tmp_path)
    put = client.put(f"/api/jobs/{job_id}/texts", json={"texts": [
        {"overlay_id": "txt_amb00001", "text": "Primeiro", "start_s": 0.0, "duration_s": 2.0},
        {"overlay_id": "txt_amb00002", "text": "Segundo", "start_s": 0.0, "duration_s": 2.0}]})
    assert put.status_code == 200, put.text
    resp = client.post("/api/chat", json={
        "message": "Muda o texto para 'X'", "job_id": job_id})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["needs_confirmation"] is False
    assert body["pending_tool_calls"] == []
