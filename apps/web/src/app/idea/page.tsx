"use client";

/* Dev-only harness for the shared SceneRenderer (idea-to-video prototype).
 * NOT a product page: it loads a local fixture storyboard so the engine can
 * be previewed and frame-captured deterministically. The Studio will mount
 * SceneRenderer with real storyboards; this route stays out of the product.
 */

import { useEffect, useRef, useState } from "react";
import SceneRenderer, { type Board, type SceneRendererHandle } from "@/components/SceneRenderer";

export default function IdeaPage() {
  const [board, setBoard] = useState<Board | null>(null);
  const [time, setTime] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [boardPath, setBoardPath] = useState("/idea-fixtures/asteroid.json");
  const rendererRef = useRef<SceneRendererHandle>(null);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const src = params.get("board") || "/idea-fixtures/asteroid.json";
    setBoardPath(src);
    fetch(src)
      .then((r) => r.json())
      .then((b: Board) => setBoard(b));
  }, []);

  useEffect(() => {
    if (!board) return;
    const params = new URLSearchParams(window.location.search);
    const t = params.get("t");
    if (t !== null) {
      const ms = Math.max(0, Math.min(Number(t) || 0, board.duration_seconds * 1000));
      rendererRef.current?.seek(ms);
      setTime(ms);
    }
    (window as unknown as { __idea?: object }).__idea = {
      seek: (ms: number) => {
        rendererRef.current?.seek(ms);
        setTime(ms);
      },
      durationMs: board.duration_seconds * 1000,
      debug: () => rendererRef.current?.debug(),
    };
    // READY is set by onReady (fonts + images decoded), not here.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [board]);

  return (
    <div style={{ background: "#000", minHeight: "100vh", display: "flex", flexDirection: "column", alignItems: "center", gap: 12, padding: 16 }}>
      <div style={{ color: "#fff", fontSize: 14 }}>{board?.project_title ?? "A carregar…"}</div>
      {board && (
        <SceneRenderer
          ref={rendererRef}
          board={board}
          assetBasePath={boardPath.split("/").slice(0, -1).join("/") + "/assets"}
          onReady={() => {
            document.title = "READY";
          }}
        />
      )}
      <div style={{ display: "flex", gap: 12, alignItems: "center", color: "#fff" }}>
        <button
          onClick={() => {
            if (playing) rendererRef.current?.pause();
            else rendererRef.current?.play();
            setPlaying(!playing);
          }}
          style={{ padding: "8px 20px" }}
        >
          Play/Pause
        </button>
        <input type="range" min={0} max={board ? board.duration_seconds * 1000 : 20000} value={time} onChange={(e) => { const v = Number(e.target.value); rendererRef.current?.seek(v); setTime(v); }} style={{ width: 400 }} />
        <span>{(time / 1000).toFixed(2)}s</span>
      </div>
    </div>
  );
}
