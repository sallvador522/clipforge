"use client";

/* Idea-to-video scene engine (vertical slice).
 * Data-driven composition from a validated Storyboard JSON. Animation uses
 * ONLY the fixed builders below, mapped from the allowlisted primitives.
 * Model output never executes: unknown primitives/targets are ignored.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { createTimeline, stagger } from "animejs";

type Step = {
  primitive: string;
  target: string;
  start_ms: number;
  duration_ms: number;
  params?: Record<string, number | string | boolean>;
  ease?: string;
};

type Scene = {
  scene_id: string;
  duration_ms: number;
  visual_description: string;
  on_screen_text: string[];
  animation_sequence: Step[];
};

type Board = {
  project_title: string;
  duration_seconds: number;
  output_fps: number;
  scenes: Scene[];
  asset_plan: { asset_id: string; scene_ids: string[] }[];
};

const W = 720;
const H = 1280;

function mulberry32(seed: number) {
  return () => {
    seed |= 0;
    seed = (seed + 0x6d2b79f5) | 0;
    let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function assetForScene(board: Board, sceneId: string): string {
  const hit = board.asset_plan.find((a) => a.scene_ids.includes(sceneId));
  return hit ? `/idea-fixtures/assets/${hit.asset_id}.png` : "";
}

export default function IdeaPage() {
  const [board, setBoard] = useState<Board | null>(null);
  const [time, setTime] = useState(0);
  const stageRef = useRef<HTMLDivElement>(null);
  const tlRef = useRef<ReturnType<typeof createTimeline> | null>(null);

  useEffect(() => {
    fetch("/idea-fixtures/asteroid.json")
      .then((r) => r.json())
      .then((b: Board) => setBoard(b));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Runs after React commits the scenes to the DOM, so every
  // [data-scene]/[data-el] target exists when the timeline is built.
  // (Building inside requestAnimationFrame raced the commit and produced
  // empty timelines.)
  useEffect(() => {
    if (!board) return;
    buildTimeline(board);
    const params = new URLSearchParams(window.location.search);
    const t = params.get("t");
    if (t !== null) {
      seekTo(Math.max(0, Math.min(Number(t) || 0, board.duration_seconds * 1000)));
    }
    document.title = "READY";
    (window as unknown as { __idea?: object }).__idea = {
      seek: (ms: number) => seekTo(ms),
      durationMs: board.duration_seconds * 1000,
      debug: () => ({
        currentTime: tlRef.current?.currentTime,
        duration: tlRef.current?.duration,
      }),
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [board]);

  const seekTo = (ms: number) => {
    tlRef.current?.seek(ms, true);
    setTime(ms);
  };

  const buildTimeline = (b: Board) => {
    const root = stageRef.current;
    if (!root) return;
    tlRef.current?.revert();
    const tl = createTimeline({ autoplay: false, defaults: { ease: "outQuad" } });
    let offset = 0;
    const easeOf = (s: Step) =>
      s.ease === "inQuad" ? "inQuad" : s.ease === "linear" ? "linear" : "outQuad";
    b.scenes.forEach((scene, si) => {
      const sec = root.querySelector<HTMLElement>(`[data-scene="${scene.scene_id}"]`);
      if (!sec) return;
      tl.set(sec, { opacity: 0 }, offset);
      tl.set(sec, { opacity: 1 }, offset + 1);
      if (si > 0) {
        const prev = root.querySelector<HTMLElement>(`[data-scene="${b.scenes[si - 1].scene_id}"]`);
        if (prev) tl.set(prev, { opacity: 0 }, offset);
      }
      for (const step of scene.animation_sequence) {
        const at = offset + step.start_ms;
        const d = step.duration_ms;
        const ease = easeOf(step);
        const el = (sel: string) => sec.querySelector<HTMLElement>(`[data-el="${sel}"]`);
        switch (step.primitive) {
          case "fade": {
            const n = el(step.target);
            if (n) {
              tl.set(n, { opacity: 0 }, at);
              tl.add(n, { opacity: [0, 1], duration: d, ease }, at);
            }
            break;
          }
          case "slide": {
            const n = el(step.target);
            if (n) {
              tl.set(n, { y: 80, opacity: 0 }, at);
              tl.add(n, { y: [80, 0], opacity: [0, 1], duration: d, ease }, at);
            }
            break;
          }
          case "text_reveal": {
            const n = el(step.target);
            if (n) tl.add(n, { opacity: [0, 1], y: [40, 0], duration: d, ease }, at);
            break;
          }
          case "kinetic_typography": {
            const n = el(step.target);
            if (n) {
              const chars = Array.from(n.querySelectorAll<HTMLElement>(".kch"));
              const each = Math.max(120, d / Math.max(1, chars.length));
              chars.forEach((ch, i) => {
                tl.add(ch, { opacity: [0, 1], y: [30, 0], duration: each, ease }, at + i * 40);
              });
            }
            break;
          }
          case "camera_zoom": {
            const from = Number(step.params?.from_scale ?? 1);
            const to = Number(step.params?.to_scale ?? 1.1);
            tl.set(sec, { scale: from }, offset);
            tl.add(sec, { scale: [from, to], duration: d, ease: "linear" }, at);
            break;
          }
          case "camera_pan": {
            const fx = Number(step.params?.from_x ?? 0.5) * W;
            const fy = Number(step.params?.from_y ?? 0.5) * H;
            const tx = Number(step.params?.to_x ?? 0.5) * W;
            const ty = Number(step.params?.to_y ?? 0.5) * H;
            tl.set(sec, { x: W / 2 - fx, y: H / 2 - fy }, offset);
            tl.add(sec, { x: [W / 2 - fx, W / 2 - tx], y: [H / 2 - fy, H / 2 - ty], duration: d, ease: "linear" }, at);
            break;
          }
          case "parallax": {
            const layers = sec.querySelectorAll<HTMLElement>("[data-layer]");
            layers.forEach((layer, i) => {
              tl.add(layer, { y: [0, -30 * (i + 1)], duration: d, ease: "linear" }, at);
            });
            break;
          }
          case "motion_path": {
            const n = el(step.target);
            if (n) {
              const fx = Number(step.params?.from_x ?? 0) * W;
              const fy = Number(step.params?.from_y ?? 0) * H;
              const tx = Number(step.params?.to_x ?? 1) * W;
              const ty = Number(step.params?.to_y ?? 1) * H;
              tl.set(n, { x: fx, y: fy }, offset);
              tl.add(n, { x: [fx, tx], y: [fy, ty], duration: d, ease }, at);
            }
            break;
          }
          case "particle_burst": {
            const host = el(step.target);
            if (host) {
              const count = Math.min(160, Number(step.params?.count ?? 60));
              const rand = mulberry32(si * 1000 + 7);
              const dots: HTMLElement[] = [];
              for (let i = 0; i < count; i++) {
                const dot = document.createElement("div");
                dot.className = "particle";
                host.appendChild(dot);
                dots.push(dot);
              }
              dots.forEach((dot, i) => {
                const ang = rand() * Math.PI * 2;
                const dist = 60 + rand() * 200;
                tl.set(dot, { x: 0, y: 0, opacity: 0 }, at);
                tl.add(dot, { opacity: [0.9, 0], x: Math.cos(ang) * dist, y: Math.sin(ang) * dist, duration: d, ease: "outQuad" }, at + (i % 10) * 20);
              });
            }
            break;
          }
          case "shockwave_ring": {
            const n = el(step.target);
            if (n) {
              const from = Number(step.params?.from_r ?? 0.05) * W;
              const to = Number(step.params?.to_r ?? 0.9) * W;
              tl.set(n, { width: 0, height: 0, opacity: 0 }, offset);
              tl.set(n, { width: from * 2, height: from * 2, opacity: 0.9 }, at);
              tl.add(n, { width: to * 2, height: to * 2, opacity: [0.9, 0], duration: d, ease: "outQuad" }, at);
            }
            break;
          }
          case "flash": {
            const n = el("flash");
            if (n) {
              tl.set(n, { opacity: 0 }, at);
              tl.add(n, { opacity: [0, 1, 0], duration: d, ease: "linear" }, at);
            }
            break;
          }
          case "counter": {
            const n = el(step.target);
            if (n) {
              const from = Number(step.params?.from ?? 0);
              const to = Number(step.params?.to ?? 100);
              const unit = String(step.params?.unit ?? "");
              const obj = { v: from };
              tl.add(obj, { v: to, duration: d, ease: "linear", onUpdate: () => {
                if (n) n.textContent = `${Math.round(obj.v)}${unit ? ` ${unit}` : ""}`;
              } }, at);
            }
            break;
          }
          case "chart_bar": {
            const bars = sec.querySelectorAll<HTMLElement>(`[data-el="${step.target}"] .bar`);
            bars.forEach((bar, i) => {
              const heights = [0.5, 0.8, 1];
              const target = heights[i % 3] ?? 1;
              tl.set(bar, { scaleY: 0.05 }, at);
              tl.add(bar, { scaleY: [0.05, target], duration: d, ease }, at + i * 150);
            });
            break;
          }
          case "svg_draw": {
            const path = sec.querySelector<SVGPathElement>(`[data-el="${step.target}"] path`);
            if (path) {
              const len = 600;
              tl.set(path, { strokeDasharray: len, strokeDashoffset: len }, at);
              tl.add(path, { strokeDashoffset: [len, 0], duration: d, ease: "linear" }, at);
            }
            break;
          }
          default:
            break;
        }
      }
      offset += scene.duration_ms;
    });
    tlRef.current = tl;
  };

  const onPlay = useCallback(() => {
    const tl = tlRef.current;
    if (!tl) return;
    if (tl.paused) tl.play();
    else tl.pause();
  }, []);

  const kinetic = (text: string) => (
    <>
      {text.split("").map((ch, i) => (
        <span key={i} className="kch" style={{ display: "inline-block", opacity: 0 }}>
          {ch === " " ? " " : ch}
        </span>
      ))}
    </>
  );

  return (
    <div style={{ background: "#000", minHeight: "100vh", display: "flex", flexDirection: "column", alignItems: "center", gap: 12, padding: 16 }}>
      <div style={{ color: "#fff", fontSize: 14 }}>{board?.project_title ?? "A carregar…"}</div>
      <div id="idea-stage" ref={stageRef} style={{ position: "relative", width: W, height: H, overflow: "hidden", background: "#05060f" }}>
        {board?.scenes.map((scene) => {
          const used = new Set(scene.animation_sequence.map((s) => s.target));
          return (
          <section key={scene.scene_id} data-scene={scene.scene_id} style={{ position: "absolute", inset: 0, opacity: 0 }}>
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img data-layer="bg" src={assetForScene(board, scene.scene_id)} alt="" style={{ position: "absolute", inset: 0, width: "100%", height: "100%", objectFit: "cover" }} />
            {used.has("asteroid") && <div data-el="asteroid" style={{ position: "absolute", left: 0, top: 0, width: 90, height: 90, borderRadius: "50%", background: "radial-gradient(circle at 35% 35%, #6b6259, #241f1b 70%)", boxShadow: "0 0 40px rgba(255,150,60,.35)" }} />}
            {used.has("plasma_trail") && <div data-el="plasma_trail" style={{ position: "absolute", left: "50%", top: "55%", width: 0, height: 0 }} />}
            {used.has("shockwave") && <div data-el="shockwave" style={{ position: "absolute", left: "50%", top: "72%", transform: "translate(-50%,-50%)", borderRadius: "50%", border: "6px solid rgba(255,200,120,.9)" }} />}
            {used.has("flash") && <div data-el="flash" style={{ position: "absolute", inset: 0, background: "#fff", opacity: 0 }} />}
            {used.has("divider") && (
            <svg data-el="divider" width={W} height={H} style={{ position: "absolute", inset: 0 }}>
              <path d="M60,1100 L660,1100" stroke="#ffb36b" strokeWidth="4" fill="none" />
            </svg>
            )}
            <div style={{ position: "absolute", left: 40, right: 40, top: 120 }}>
              {scene.on_screen_text.map((t, i) => (
                <div key={i} data-el={i === 0 ? "title" : `line${i}`} style={{ color: "#fff", fontFamily: "Arial, sans-serif", fontWeight: 800, fontSize: i === 0 ? 54 : 34, textShadow: "0 2px 18px rgba(0,0,0,.8)", marginBottom: 12 }}>
                  {kinetic(t)}
                </div>
              ))}
            </div>
            {used.has("conclusion") && (
            <div data-el="conclusion" style={{ position: "absolute", left: 40, right: 40, bottom: 220, color: "#ffd9a8", fontFamily: "Arial, sans-serif", fontSize: 28, opacity: 0 }}>
              {kinetic(scene.on_screen_text[scene.on_screen_text.length - 1] ?? "")}
            </div>
            )}
            {used.has("counter") && <div data-el="counter" style={{ position: "absolute", left: 40, top: 560, color: "#fff", fontFamily: "Arial, sans-serif", fontWeight: 800, fontSize: 72 }}>0 m</div>}
            {used.has("chart") && (
            <div data-el="chart" style={{ position: "absolute", left: 40, right: 40, bottom: 120, display: "flex", gap: 24, alignItems: "flex-end", height: 300 }}>
              {[0, 1, 2].map((i) => (
                <div key={i} className="bar" style={{ flex: 1, background: "linear-gradient(to top,#ff7a2f,#ffc46b)", height: 280, transformOrigin: "bottom" }} />
              ))}
            </div>
            )}
          </section>
          );
        })}
      </div>
      <div style={{ display: "flex", gap: 12, alignItems: "center", color: "#fff" }}>
        <button onClick={onPlay} style={{ padding: "8px 20px" }}>Play/Pause</button>
        <input type="range" min={0} max={board ? board.duration_seconds * 1000 : 20000} value={time} onChange={(e) => seekTo(Number(e.target.value))} style={{ width: 400 }} />
        <span>{(time / 1000).toFixed(2)}s</span>
      </div>
    </div>
  );
}
