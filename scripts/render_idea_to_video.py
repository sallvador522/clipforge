"""Offline idea-to-video render pipeline (vertical slice, no billing).

Captures a validated storyboard from the Anime.js scene engine with
deterministic seeks, encodes with FFmpeg, and runs deterministic QA.
All inputs are local fixtures; no network calls except localhost.

Usage: python scripts/render_idea_to_video.py [--fps 24] [--out storage/idea_poc]
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages" / "contracts"))

from clipforge_contracts.storyboard import Storyboard  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--storyboard", default="apps/web/public/idea-fixtures/asteroid.json")
    parser.add_argument("--base-url", default="http://localhost:3000/idea")
    parser.add_argument("--board", default=None)
    parser.add_argument("--fps", type=int, default=24)
    parser.add_argument("--out", default="storage/idea_poc")
    return parser.parse_args()


LAYOUT_PROBE_JS = """() => {
  const stage = document.querySelector('#idea-stage').getBoundingClientRect();
  // Only typography must never clip. Effect elements (motion entries,
  // shockwave rings, flashes, dividers) bleed past the frame by design.
  const TEXT_ELS = ['title', 'conclusion', 'counter'];
  const bad = [];
  document.querySelectorAll('#idea-stage section').forEach((sec) => {
    if (getComputedStyle(sec).opacity === '0') return;
    sec.querySelectorAll('[data-el]').forEach((el) => {
      const id = el.dataset.el || '';
      const isText = TEXT_ELS.includes(id) || id.startsWith('line');
      if (!isText) return;
      if (getComputedStyle(el).opacity === '0') return;
      const r = el.getBoundingClientRect();
      if (r.width < 2 || r.height < 2) return;
      const margin = 8;
      if (r.left < stage.left - margin || r.top < stage.top - margin ||
          r.right > stage.right + margin || r.bottom > stage.bottom + margin) {
        bad.push({
          scene: sec.dataset.scene, el: id,
          rect: [Math.round(r.left), Math.round(r.top), Math.round(r.width), Math.round(r.height)],
        });
      }
    });
  });
  return bad;
}"""


def layout_qa(page, board: Storyboard) -> list[dict]:
    """Fail fast on text/graphics escaping the 720x1280 stage.

    Seeks to the start/middle/end of every scene and reports visible
    [data-el] boxes outside the stage bounds. Runs before capture so a
    layout regression never costs a full render.
    """
    violations: list[dict] = []
    offset = 0
    for scene in board.scenes:
        for t in (offset + 1, offset + scene.duration_ms // 2, offset + scene.duration_ms - 1):
            page.evaluate(f"window.__idea.seek({t})")
            page.wait_for_timeout(250)
            for bad in page.evaluate(LAYOUT_PROBE_JS):
                violations.append({"t_ms": t, **bad})
        offset += scene.duration_ms
    return violations


def capture(board: Storyboard, args: argparse.Namespace, frames_dir: Path) -> int:
    from playwright.sync_api import sync_playwright

    total_ms = board.duration_seconds * 1000
    count = board.duration_seconds * args.fps
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": 800, "height": 1400})
        url = args.base_url
        if args.board:
            url += ("&" if "?" in url else "?") + f"board={args.board}"
        page.goto(url, wait_until="domcontentloaded", timeout=120000)
        page.wait_for_function("document.title === 'READY'", timeout=60000)
        # Guard against a stale dev-server build or a missed first paint:
        # retry the seek before refusing to capture identical frames.
        opacity = "unknown"
        debug = {}
        for _ in range(3):
            page.evaluate("window.__idea.seek(2500)")
            page.wait_for_timeout(400)
            debug = page.evaluate("JSON.stringify(window.__idea.debug())")
            opacity = page.evaluate(
                "getComputedStyle(document.querySelector('[data-scene=\"scene_1\"]')).opacity"
            )
            if opacity == "1":
                break
        if opacity != "1":
            browser.close()
            raise RuntimeError(
                f"Scene engine did not respond to seek (scene_1 opacity={opacity}, "
                f"timeline={debug}); refusing to capture identical frames."
            )
        violations = layout_qa(page, board)
        if violations:
            browser.close()
            raise RuntimeError(
                f"Layout QA failed: {len(violations)} element(s) outside the stage: "
                f"{json.dumps(violations[:5])}"
            )
        have = {p.name for p in frames_dir.glob("frame_*.png")}
        missing = [i for i in range(count) if f"frame_{i:05d}.png" not in have]
        if have and missing:
            print(f"Resuming capture: {len(missing)}/{count} frames missing; reusing the rest.")
        for i in missing:
            t = min(int(i * 1000 / args.fps), total_ms - 1)
            page.evaluate(f"window.__idea.seek({t})")
            page.locator("#idea-stage").screenshot(path=str(frames_dir / f"frame_{i:05d}.png"))
        browser.close()
    return count


def encode(frames_dir: Path, out_path: Path, fps: int, width: int, height: int) -> None:
    command = [
        "ffmpeg", "-y",
        "-framerate", str(fps),
        "-i", str(frames_dir / "frame_%05d.png"),
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-vf", f"scale={width}:{height}",
        "-movflags", "+faststart",
        str(out_path),
    ]
    result = subprocess.run(command, capture_output=True, text=True, timeout=600)
    if result.returncode != 0:
        raise RuntimeError(f"FFmpeg encode failed: {result.stderr.strip()[-500:]}")


def probe(path: Path) -> dict:
    raw = subprocess.run(
        ["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
        capture_output=True, text=True, timeout=120,
    )
    if raw.returncode != 0:
        raise RuntimeError(f"ffprobe failed: {raw.stderr.strip()[-300:]}")
    return json.loads(raw.stdout)


def qa_frames(frames_dir: Path, expected: int) -> dict:
    files = sorted(frames_dir.glob("frame_*.png"))
    missing = expected - len(files)
    black = 0
    frozen_runs = 0
    previous = None
    run = 0
    for path in files:
        img = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
        if img is None:
            raise RuntimeError(f"Unreadable frame {path.name}; refusing to encode unverified media.")
        if float(np.mean(img)) < 2.0:
            black += 1
        if previous is not None and np.array_equal(img, previous):
            run += 1
            if run >= 11:
                frozen_runs += 1
        else:
            run = 0
        previous = img
    return {"captured": len(files), "missing": missing, "black": black, "frozen_runs": frozen_runs}


def main() -> int:
    args = parse_args()
    board_path = ROOT / args.storyboard
    board = Storyboard.model_validate(json.loads(board_path.read_text(encoding="utf-8")))
    out_dir = ROOT / args.out
    frames_dir = out_dir / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "idea.mp4"

    started = time.perf_counter()
    expected = capture(board, args, frames_dir)
    capture_seconds = time.perf_counter() - started
    checks = qa_frames(frames_dir, expected)
    encode(frames_dir, out_path, args.fps, 720, 1280)
    info = probe(out_path)
    video = next(s for s in info["streams"] if s["codec_type"] == "video")
    report = {
        "storyboard": board.project_title,
        "duration_seconds": board.duration_seconds,
        "fps": args.fps,
        "expected_frames": expected,
        "capture_seconds": round(capture_seconds, 1),
        "capture_fps": round(expected / max(capture_seconds, 0.01), 2),
        "qa": checks,
        "output": {
            "path": str(out_path.relative_to(ROOT)),
            "bytes": out_path.stat().st_size,
            "width": int(video["width"]),
            "height": int(video["height"]),
            "nb_frames": video.get("nb_frames"),
            "duration": info["format"].get("duration"),
        },
    }
    (out_dir / "qa_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    failed = checks["missing"] != 0 or checks["black"] > expected * 0.05
    if failed:
        print("QA FAILED: missing or excessively black frames.")
        return 1
    if video.get("nb_frames") is not None and int(video["nb_frames"]) != expected:
        print(f"QA FAILED: encoded {video.get('nb_frames')} frames, expected {expected}.")
        return 1
    print("QA PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
