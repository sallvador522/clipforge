"use client";

/* Shared scene renderer: the single animation runtime for idea-to-video.
 *
 * Data-driven composition from a validated Storyboard. Animation uses ONLY
 * the fixed builders below, mapped from the allowlisted primitives. Model
 * output never executes: unknown primitives/targets are ignored.
 *
 * Used by the Studio preview AND by headless deterministic export (same
 * component, same storyboard JSON). The Chromium capture surface is an
 * implementation detail, not a product page.
 */

import { forwardRef, useEffect, useImperativeHandle, useRef } from "react";
import { createTimeline } from "animejs";

export type Step = {
  primitive: string;
  target: string;
  start_ms: number;
  duration_ms: number;
  params?: Record<string, number | string | boolean>;
  ease?: string;
};

export type Scene = {
  scene_id: string;
  duration_ms: number;
  visual_description: string;
  on_screen_text: string[];
  animation_sequence: Step[];
};

export type Board = {
  project_title: string;
  duration_seconds: number;
  output_fps: number;
  scenes: Scene[];
  asset_plan: { asset_id: string; scene_ids: string[] }[];
};

export type SceneRendererHandle = {
  seek: (ms: number) => void;
  play: () => void;
  pause: () => void;
  durationMs: number;
  debug: () => { currentTime: number | undefined; duration: number | undefined };
};

type Props = {
  board: Board;
  /** Base URL for scene background assets (stable asset refs resolve under it). */
  assetBasePath: string;
  /** Called once the engine is built AND fonts/images are ready to paint. */
  onReady?: () => void;
  /** When false the renderer stays inert until `play()` is called (preview). */
  startPaused?: boolean;
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

const SceneRenderer = forwardRef<SceneRendererHandle, Props>(function SceneRenderer(
  { board, assetBasePath, onReady, startPaused = true }: Props,
  ref
) {
  const stageRef = useRef<HTMLDivElement>(null);
  const tlRef = useRef<ReturnType<typeof createTimeline> | null>(null);
  const readyRef = useRef(false);

  const assetForScene = (sceneId: string): string | null => {
    const hit = board.asset_plan.find((a) => a.scene_ids.includes(sceneId));
    return hit ? `${assetBasePath}/${hit.asset_id}.png` : null;
  };

  const sceneHue = (sceneId: string): number => {
    let h = 0;
    for (let i = 0; i < sceneId.length; i++) h = (h * 31 + sceneId.charCodeAt(i)) % 360;
    return h;
  };

  // Runs after React commits the scenes to the DOM, so every
  // [data-scene]/[data-el] target exists when the timeline is built.
  // (Building inside requestAnimationFrame raced the commit and produced
  // empty timelines.)
  useEffect(() => {
    buildTimeline(board);
    const markReady = async () => {
      try {
        await document.fonts.ready;
        const imgs = Array.from(
          stageRef.current?.querySelectorAll<HTMLImageElement>("img") ?? []
        );
        await Promise.all(imgs.map((img) => img.decode().catch(() => undefined)));
      } finally {
        if (!readyRef.current) {
          readyRef.current = true;
          onReady?.();
        }
      }
    };
    void markReady();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [board]);

  useImperativeHandle(ref, () => ({
    seek: (ms: number) => seekTo(ms),
    play: () => tlRef.current?.play(),
    pause: () => tlRef.current?.pause(),
    durationMs: board.duration_seconds * 1000,
    debug: () => ({
      currentTime: tlRef.current?.currentTime,
      duration: tlRef.current?.duration,
    }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }));

  const syncCounters = (ms: number) => {
    // onUpdate callbacks are muted during seek, so counters are set
    // deterministically from the storyboard timing instead.
    stageRef.current?.querySelectorAll<HTMLElement>("[data-cfrom]").forEach((n) => {
      const from = Number(n.dataset.cfrom ?? 0);
      const to = Number(n.dataset.cto ?? 0);
      const start = Number(n.dataset.cstart ?? 0);
      const dur = Number(n.dataset.cdur ?? 1);
      const unit = n.dataset.cunit ?? "";
      const p = Math.min(1, Math.max(0, (ms - start) / dur));
      n.textContent = `${Math.round(from + (to - from) * p)}${unit ? ` ${unit}` : ""}`;
    });
  };

  const seekTo = (ms: number) => {
    tlRef.current?.seek(ms, true);
    syncCounters(ms);
  };

  const buildTimeline = (b: Board) => {
    const root = stageRef.current;
    if (!root) return;
    tlRef.current?.revert();
    const tl = createTimeline({ autoplay: !startPaused, defaults: { ease: "outQuad" } });
    // Hold helper: completed tweens don't stick on a never-played timeline
    // under seek-only rendering, so pin each tween's end values with a set.
    type TweenProps = { [k: string]: number | string | boolean | number[] };
    const hold = (target: object, props: TweenProps, at: number, d: number) => {
      const end: TweenProps = {};
      for (const [k, v] of Object.entries(props)) {
        if (["duration", "ease", "delay", "onUpdate", "onBegin", "onComplete"].includes(k)) continue;
        end[k] = Array.isArray(v) ? (v[v.length - 1] as number) : v;
      }
      tl.set(target, end, at + d);
    };
    const addHold = (target: object, props: TweenProps, at: number, d: number) => {
      tl.add(target, props, at);
      hold(target, props, at, d);
    };
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
              addHold(n, { opacity: [0, 1], duration: d, ease }, at, d);
            }
            break;
          }
          case "slide": {
            const n = el(step.target);
            if (n) {
              tl.set(n, { y: 80, opacity: 0 }, at);
              addHold(n, { y: [80, 0], opacity: [0, 1], duration: d, ease }, at, d);
            }
            break;
          }
          case "text_reveal": {
            const n = el(step.target);
            if (n) {
              tl.set(n, { opacity: 0, y: 40 }, at);
              addHold(n, { opacity: [0, 1], y: [40, 0], duration: d, ease }, at, d);
            }
            break;
          }
          case "kinetic_typography": {
            const n = el(step.target);
            if (n) {
              const chars = Array.from(n.querySelectorAll<HTMLElement>(".kch"));
              const each = Math.max(120, d / Math.max(1, chars.length));
              chars.forEach((ch, i) => {
                const t = at + i * 40;
                tl.set(ch, { opacity: 0, y: 30 }, t);
                addHold(ch, { opacity: [0, 1], y: [30, 0], duration: each, ease }, t, each);
              });
            }
            break;
          }
          case "camera_zoom": {
            const from = Number(step.params?.from_scale ?? 1);
            const to = Number(step.params?.to_scale ?? 1.1);
            // Camera moves the backdrop, never the typography: text stays
            // legible while the background drifts beneath it.
            const cam = sec.querySelector<HTMLElement>('[data-layer="bg"]') ?? sec;
            tl.set(cam, { scale: from }, offset);
            addHold(cam, { scale: [from, to], duration: d, ease: "linear" }, at, d);
            break;
          }
          case "camera_pan": {
            const fx = Number(step.params?.from_x ?? 0.5) * W;
            const fy = Number(step.params?.from_y ?? 0.5) * H;
            const tx = Number(step.params?.to_x ?? 0.5) * W;
            const ty = Number(step.params?.to_y ?? 0.5) * H;
            const cam = sec.querySelector<HTMLElement>('[data-layer="bg"]') ?? sec;
            tl.set(cam, { x: W / 2 - fx, y: H / 2 - fy }, offset);
            addHold(cam, { x: [W / 2 - fx, W / 2 - tx], y: [H / 2 - fy, H / 2 - ty], duration: d, ease: "linear" }, at, d);
            break;
          }
          case "parallax": {
            const layers = sec.querySelectorAll<HTMLElement>("[data-layer]");
            layers.forEach((layer, i) => {
              addHold(layer, { y: [0, -30 * (i + 1)], duration: d, ease: "linear" }, at, d);
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
              addHold(n, { x: [fx, tx], y: [fy, ty], duration: d, ease }, at, d);
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
              addHold(n, { width: to * 2, height: to * 2, opacity: [0.9, 0], duration: d, ease: "outQuad" }, at, d);
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
              n.dataset.cfrom = String(from);
              n.dataset.cto = String(to);
              n.dataset.cstart = String(at);
              n.dataset.cdur = String(d);
              n.dataset.cunit = unit;
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
              addHold(bar, { scaleY: [0.05, target], duration: d, ease }, at + i * 150, d);
            });
            break;
          }
          case "svg_draw": {
            const path = sec.querySelector<SVGPathElement>(`[data-el="${step.target}"] path`);
            if (path) {
              const len = 600;
              tl.set(path, { strokeDasharray: len, strokeDashoffset: len }, at);
              addHold(path, { strokeDashoffset: [len, 0], duration: d, ease: "linear" }, at, d);
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

  const kinetic = (text: string, animated: boolean) => {
    if (!animated) return <>{text}</>;
    return (
      <>
        {text.split("").map((ch, i) => (
          <span key={i} className="kch" style={{ display: "inline-block", opacity: 0 }}>
            {ch === " " ? " " : ch}
          </span>
        ))}
      </>
    );
  };

  return (
    <div id="idea-stage" ref={stageRef} style={{ position: "relative", width: W, height: H, overflow: "hidden", background: "#05060f" }}>
      {board.scenes.map((scene) => {
        const used = new Set(scene.animation_sequence.map((s) => s.target));
        return (
        <section key={scene.scene_id} data-scene={scene.scene_id} style={{ position: "absolute", inset: 0, opacity: 0 }}>
          {(() => {
            const src = assetForScene(scene.scene_id);
            if (src) {
              // eslint-disable-next-line @next/next/no-img-element
              return <img data-layer="bg" src={src} alt="" style={{ position: "absolute", inset: 0, width: "100%", height: "100%", objectFit: "cover" }} />;
            }
            // Programmatic backdrop: deterministic gradient, no raster needed.
            const hue = sceneHue(scene.scene_id);
            return <div data-layer="bg" style={{ position: "absolute", inset: 0, background: `linear-gradient(160deg, hsl(${hue},42%,10%), hsl(${(hue + 50) % 360},48%,20%))` }} />;
          })()}
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
            {scene.on_screen_text.map((t, i) => {
              const elId = i === 0 ? "title" : `line${i}`;
              const animated = scene.animation_sequence.some(
                (s) => s.primitive === "kinetic_typography" && s.target === elId
              );
              return (
              <div key={i} data-el={elId} style={{ color: "#fff", fontFamily: "Arial, sans-serif", fontWeight: 800, fontSize: i === 0 ? 54 : 34, textShadow: "0 2px 18px rgba(0,0,0,.8)", marginBottom: 12 }}>
                {kinetic(t, animated)}
              </div>
              );
            })}
          </div>
          {used.has("conclusion") && (
          <div data-el="conclusion" style={{ position: "absolute", left: 40, right: 40, bottom: 220, color: "#ffd9a8", fontFamily: "Arial, sans-serif", fontSize: 28, opacity: 0 }}>
            {kinetic(scene.on_screen_text[scene.on_screen_text.length - 1] ?? "", scene.animation_sequence.some((s) => s.primitive === "kinetic_typography" && s.target === "conclusion"))}
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
  );
});

export default SceneRenderer;
