"""Deterministic idea renderer: capture the scene engine, encode, verify.

The browser is only a capture surface. The worker opens
`<studio>/render/<idea_id>` (a noindex page that fetches a validated manifest
from the API), seeks frame by frame through the shared SceneRenderer, encodes
with FFmpeg and refuses to deliver anything that fails deterministic QA.

No network access except the local Studio and API. No AI calls happen here.
"""

from __future__ import annotations

import json
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

from clipforge_contracts import sha256_file
from clipforge_contracts.storyboard import Storyboard


class IdeaRenderError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class IdeaCancelled(IdeaRenderError):
    def __init__(self) -> None:
        super().__init__("cancelled_by_user", "Render cancelado pelo utilizador.")


@dataclass
class IdeaRenderRequest:
    idea_id: str
    storyboard: Storyboard
    asset_urls: dict[str, str] = field(default_factory=dict)
    output_dir: Path = Path(".")
    width: int = 720
    height: int = 1280
    fps: int = 24
    studio_url: str = "http://localhost:3000"
    keep_frames: bool = False


LAYOUT_PROBE_JS = """() => {
  const stage = document.querySelector('#idea-stage').getBoundingClientRect();
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


def _layout_qa(page, board: Storyboard) -> list[dict]:
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


def _check_studio(studio_url: str) -> None:
    import httpx

    url = studio_url.rstrip("/") + "/"
    try:
        response = httpx.get(url, timeout=10.0, follow_redirects=True)
    except httpx.HTTPError as exc:
        raise IdeaRenderError(
            "studio_unreachable",
            f"O Studio em {url} não respondeu. Arranca o frontend (next start) antes de renderizar.",
        ) from exc
    if response.status_code >= 500:
        raise IdeaRenderError(
            "studio_unreachable",
            f"O Studio em {url} respondeu com HTTP {response.status_code}.",
        )


def _url_ok(url: str) -> bool:
    import httpx

    # GET, not HEAD: the file route answers GET only. Streaming + immediate
    # close checks servability without downloading the whole plate.
    try:
        with httpx.stream("GET", url, timeout=15.0, follow_redirects=True) as response:
            return response.status_code == 200
    except httpx.HTTPError:
        return False


def _check_assets(board: Storyboard, asset_urls: dict[str, str]) -> list[str]:
    missing: list[str] = []
    for asset in board.asset_plan:
        url = asset_urls.get(asset.asset_id)
        if not url:
            # Not generated on purpose (user kept the scene programmatic).
            continue
        if not _url_ok(url):
            missing.append(asset.asset_id)
    return missing


def qa_frames(frames_dir: Path, expected: int) -> dict:
    import cv2
    import numpy as np

    files = sorted(frames_dir.glob("frame_*.png"))
    missing = expected - len(files)
    black = 0
    frozen_frames = 0
    frozen_runs = 0
    previous = None
    run = 0
    for path in files:
        img = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
        if img is None:
            raise IdeaRenderError("unreadable_frame", f"Frame ilegível: {path.name}.")
        if float(np.mean(img)) < 2.0:
            black += 1
        if previous is not None and np.array_equal(img, previous):
            run += 1
            if run == 11:
                frozen_runs += 1
            if run >= 11:
                frozen_frames += 1
        else:
            run = 0
        previous = img
    return {
        "captured": len(files),
        "missing": missing,
        "black": black,
        "frozen_frames": frozen_frames,
        "frozen_runs": frozen_runs,
    }


def frame_time_ms(index: int, fps: int, total_ms: int) -> int:
    """Sample time for a frame: frame centres, clamped to the timeline.

    Centres never land on exact scene boundaries, where the engine switches
    section opacity (offset → offset+1ms) and a boundary sample would capture
    a one-frame background flash.
    """
    return min(int((index + 0.5) * 1000 / fps), total_ms - 1)


def sample_time_ms(index: int, fps: int, total_ms: int, timeline_ms: int) -> int:
    """Capture time for a frame: centres, clamped to the engine timeline.

    The timeline ends at its last animation, which may be earlier than the
    project length. Sampling past it would clamp inside the engine and trip
    the advancement check on a healthy tail.
    """
    if timeline_ms <= 0:
        raise IdeaRenderError(
            "scene_engine_unresponsive",
            "O motor de cenas não reportou uma duração válida.",
        )
    return min(frame_time_ms(index, fps, total_ms), timeline_ms)


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
    result = subprocess.run(command, capture_output=True, text=True, timeout=900)
    if result.returncode != 0:
        raise IdeaRenderError("encode_failed", f"FFmpeg falhou: {result.stderr.strip()[-500:]}")


def probe(path: Path) -> dict:
    raw = subprocess.run(
        [
            "ffprobe", "-v", "error", "-count_frames",
            "-show_streams", "-show_format", "-of", "json", str(path),
        ],
        capture_output=True, text=True, timeout=300,
    )
    if raw.returncode != 0:
        raise IdeaRenderError("probe_failed", f"ffprobe falhou: {raw.stderr.strip()[-300:]}")
    return json.loads(raw.stdout)


def _parse_fps(value: str | None) -> float:
    if not value:
        return 0.0
    if "/" in value:
        numerator, _, denominator = value.partition("/")
        try:
            return float(numerator) / float(denominator or 1)
        except (ValueError, ZeroDivisionError):
            return 0.0
    try:
        return float(value)
    except ValueError:
        return 0.0


def verify_output(path: Path, *, width: int, height: int, fps: int, expected_frames: int) -> dict:
    if not path.is_file() or path.stat().st_size == 0:
        raise IdeaRenderError("render_not_verified", "O ficheiro renderizado está vazio ou em falta.")
    info = probe(path)
    streams = info.get("streams") or []
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    if video is None:
        raise IdeaRenderError("render_not_verified", "O ficheiro não tem stream de vídeo.")
    actual_width = int(video.get("width") or 0)
    actual_height = int(video.get("height") or 0)
    if (actual_width, actual_height) != (width, height):
        raise IdeaRenderError(
            "render_not_verified",
            f"Dimensões {actual_width}x{actual_height}; esperado {width}x{height}.",
        )
    actual_fps = _parse_fps(video.get("avg_frame_rate") or video.get("r_frame_rate"))
    if abs(actual_fps - fps) > 0.05:
        raise IdeaRenderError("render_not_verified", f"FPS {actual_fps:.3f}; esperado {fps}.")
    frames_raw = video.get("nb_frames") or video.get("nb_read_frames")
    try:
        actual_frames = int(frames_raw)
    except (TypeError, ValueError):
        actual_frames = 0
    if actual_frames != expected_frames:
        raise IdeaRenderError(
            "render_not_verified",
            f"{actual_frames} frames codificados; esperado {expected_frames}.",
        )
    duration = float((info.get("format") or {}).get("duration") or 0.0)
    expected_duration = expected_frames / fps
    if abs(duration - expected_duration) > 0.25:
        raise IdeaRenderError(
            "render_not_verified",
            f"Duração {duration:.3f}s; esperado {expected_duration:.3f}s.",
        )
    if video.get("pix_fmt") != "yuv420p":
        raise IdeaRenderError(
            "render_not_verified", f"pix_fmt {video.get('pix_fmt')!r}; esperado yuv420p."
        )
    return {
        "width": actual_width,
        "height": actual_height,
        "fps": round(actual_fps, 3),
        "frame_count": actual_frames,
        "duration_seconds": round(duration, 3),
        "pix_fmt": video.get("pix_fmt"),
        "codec": video.get("codec_name"),
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def render_idea(
    request: IdeaRenderRequest,
    *,
    on_progress=None,
    is_cancelled=None,
) -> dict:
    """Capture, encode and verify one idea render. Raises on any QA failure."""
    from playwright.sync_api import Error as PlaywrightError
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
    from playwright.sync_api import sync_playwright

    board = request.storyboard
    total_ms = board.duration_seconds * 1000
    count = board.duration_seconds * request.fps
    frames_dir = request.output_dir / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)
    out_path = request.output_dir / "out.mp4"

    def progress(stage: str, current: int, total: int) -> None:
        if on_progress is not None:
            on_progress(stage, current, total)

    def check_cancel() -> None:
        if is_cancelled is not None and is_cancelled():
            raise IdeaCancelled()

    _check_studio(request.studio_url)
    started = time.perf_counter()

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        viewport_width = max(800, request.width + 80)
        viewport_height = max(900, request.height + 120)
        page = browser.new_page(viewport={"width": viewport_width, "height": viewport_height})
        try:
            url = f"{request.studio_url.rstrip('/')}/render/{request.idea_id}"
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=120000)
                page.wait_for_function("document.title === 'READY'", timeout=90000)
            except PlaywrightTimeoutError as exc:
                raise IdeaRenderError(
                    "render_surface_timeout",
                    "A superfície de render não ficou pronta. Verifica se o Studio e a API "
                    "estão a correr e se o storyboard carrega.",
                ) from exc
            except PlaywrightError as exc:
                raise IdeaRenderError(
                    "render_surface_error", f"O browser de captura falhou: {exc}"
                ) from exc

            opacity = "unknown"
            debug = {}
            first_scene = board.scenes[0]
            # Never probe past a short opening scene: the engine only shows
            # one scene at a time, so a fixed 2.5 s seek can land on scene 2.
            probe_ms = min(2500, max(500, first_scene.duration_ms // 2))
            selector = f'[data-scene="{first_scene.scene_id}"]'
            for _ in range(3):
                page.evaluate(f"window.__idea.seek({probe_ms})")
                page.wait_for_timeout(400)
                debug = page.evaluate("JSON.stringify(window.__idea.debug())")
                opacity = page.evaluate(
                    "(sel) => getComputedStyle(document.querySelector(sel)).opacity", selector
                )
                if opacity == "1":
                    break
            if opacity != "1":
                raise IdeaRenderError(
                    "scene_engine_unresponsive",
                    f"O motor de cenas não respondeu ao seek "
                    f"({first_scene.scene_id}, opacity={opacity}, timeline={debug}).",
                )

            missing_assets = _check_assets(board, request.asset_urls)
            if missing_assets:
                raise IdeaRenderError(
                    "asset_missing",
                    f"O storyboard referencia assets em falta: {missing_assets}.",
                )

            violations = _layout_qa(page, board)
            if violations:
                raise IdeaRenderError(
                    "layout_qa_failed",
                    f"{len(violations)} elemento(s) de texto fora do stage: "
                    f"{json.dumps(violations[:5])}",
                )

            have = {p.name for p in frames_dir.glob("frame_*.png")}
            missing = [i for i in range(count) if f"frame_{i:05d}.png" not in have]
            done = len(have)
            progress("rendering", done, count)
            # The engine timeline ends at its last animation, which may be
            # earlier than the project length (a static end card is legit
            # content). Seeks past that point clamp to the real duration, so
            # both sampling and the advancement check use it — otherwise a
            # healthy tail trips scene_engine_unresponsive.
            try:
                tl_duration = int(
                    float(page.evaluate("window.__idea.debug().duration"))
                )
            except (TypeError, ValueError):
                tl_duration = 0
            if tl_duration <= 0:
                raise IdeaRenderError(
                    "scene_engine_unresponsive",
                    "O motor de cenas não reportou uma duração válida.",
                )
            for i in missing:
                check_cancel()
                t = sample_time_ms(i, request.fps, total_ms, tl_duration)
                page.evaluate(f"window.__idea.seek({t})")
                # Fail fast when the engine does not follow the seek: a stuck
                # timeline would otherwise waste a full capture and only trip
                # the frozen-frame QA at the end.
                current = page.evaluate("window.__idea.debug().currentTime")
                try:
                    advanced = abs(float(current) - t) <= 1.0
                except (TypeError, ValueError):
                    advanced = False
                if not advanced:
                    raise IdeaRenderError(
                        "scene_engine_unresponsive",
                        f"O motor de cenas não avançou para {t}ms (timeline em {current}).",
                    )
                page.locator("#idea-stage").screenshot(
                    path=str(frames_dir / f"frame_{i:05d}.png")
                )
                done += 1
                if done % 10 == 0:
                    progress("rendering", done, count)
        finally:
            browser.close()

    capture_seconds = time.perf_counter() - started
    progress("verifying_frames", count, count)
    checks = qa_frames(frames_dir, count)
    if checks["missing"] != 0:
        raise IdeaRenderError(
            "qa_failed", f"Faltam {checks['missing']} frames; o vídeo não pode ser entregue."
        )
    if checks["black"] != 0:
        raise IdeaRenderError(
            "qa_failed", f"{checks['black']} frames pretos; o vídeo não pode ser entregue."
        )
    if checks["frozen_frames"] > max(2, int(count * 0.2)):
        raise IdeaRenderError(
            "qa_failed",
            f"{checks['frozen_frames']} frames congelados (limite {int(count * 0.2)}).",
        )

    progress("encoding", 0, 1)
    encode(frames_dir, out_path, request.fps, request.width, request.height)
    progress("verifying_output", 1, 1)
    output = verify_output(
        out_path,
        width=request.width,
        height=request.height,
        fps=request.fps,
        expected_frames=count,
    )
    return {
        "qa": {
            **checks,
            "capture_seconds": round(capture_seconds, 1),
            "capture_fps": round(count / max(capture_seconds, 0.01), 2),
            "output": output,
        },
        "output_path": str(out_path),
        "output_sha256": output["sha256"],
        "width": output["width"],
        "height": output["height"],
        "fps": output["fps"],
        "frame_count": output["frame_count"],
        "duration_seconds": output["duration_seconds"],
    }
