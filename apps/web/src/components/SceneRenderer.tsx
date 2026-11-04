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

export type SceneTextStyle = {
  family: "sans" | "serif" | "mono";
  weight: number;
  size_scale: number;
  color: string;
  align: "left" | "center" | "right";
  valign: "top" | "middle" | "lower";
  letter_spacing_em: number;
};

export type Scene = {
  scene_id: string;
  duration_ms: number;
  visual_description: string;
  on_screen_text: string[];
  text_style?: SceneTextStyle;
  backdrop_hue_deg?: number | null;
  transition_in?: string;
  transition_out?: string;
  transition_ms?: number;
  animation_sequence: Step[];
};

export type Overlay = {
  overlay_id: string;
  kind?: "text" | "image";
  text: string;
  asset_id?: string | null;
  start_ms: number;
  end_ms: number;
  style?: SceneTextStyle;
};

export type Board = {
  project_title: string;
  duration_seconds: number;
  output_fps: number;
  scenes: Scene[];
  asset_plan: AssetRef[];
  overlays?: Overlay[];
};

export type AssetRef = {
  asset_id: string;
  scene_ids: string[];
  role?: string;
};

/** Resolve one multiplane layer for a scene: backdrop or foreground band. */
export function layerAssetFor(
  plan: AssetRef[],
  assetUrls: Record<string, string> | undefined,
  assetBasePath: string,
  sceneId: string,
  role: "background" | "foreground",
): string | null {
  const hit = plan.find(
    (a) => a.scene_ids.includes(sceneId) && (a.role ?? "background") === role,
  );
  if (!hit) return null;
  if (assetUrls) return assetUrls[hit.asset_id] ?? null;
  return assetBasePath ? `${assetBasePath}/${hit.asset_id}.png` : null;
}

export function bgAssetFor(
  plan: AssetRef[],
  assetUrls: Record<string, string> | undefined,
  assetBasePath: string,
  sceneId: string,
): string | null {
  return layerAssetFor(plan, assetUrls, assetBasePath, sceneId, "background");
}

export function fgAssetFor(
  plan: AssetRef[],
  assetUrls: Record<string, string> | undefined,
  assetBasePath: string,
  sceneId: string,
): string | null {
  return layerAssetFor(plan, assetUrls, assetBasePath, sceneId, "foreground");
}

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
  assetBasePath?: string;
  /** Explicit asset URL per asset id. When present, unlisted assets stay programmatic. */
  assetUrls?: Record<string, string>;
  /** Stage size. Defaults to the vertical 720x1280 master. */
  width?: number;
  height?: number;
  /** Called once the engine is built AND fonts/images are ready to paint. */
  onReady?: () => void;
  /** When false the renderer stays inert until `play()` is called (preview). */
  startPaused?: boolean;
};

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
  { board, assetBasePath = "", assetUrls, width = 720, height = 1280, onReady, startPaused = true }: Props,
  ref
) {
  const W = width;
  const H = height;
  const stageRef = useRef<HTMLDivElement>(null);
  const tlRef = useRef<ReturnType<typeof createTimeline> | null>(null);
  const readyRef = useRef(false);

  const assetForScene = (sceneId: string): string | null =>
    bgAssetFor(board.asset_plan, assetUrls, assetBasePath, sceneId);

  const fgAssetForScene = (sceneId: string): string | null =>
    fgAssetFor(board.asset_plan, assetUrls, assetBasePath, sceneId);

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
    type TweenProps = { [k: string]: number | string | boolean | number[] | string[] };
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
    // Easing passthrough over the verified Anime.js vocabulary. Anything
    // else falls back to outQuad so an old or misspelled value can never
    // throw inside the capture browser.
    const ENGINE_EASES = new Set([
      "linear",
      "inQuad",
      "outQuad",
      "inOutQuad",
      "outExpo",
      "outCirc",
      "outBack",
      "outElastic",
      "outBounce",
    ]);
    const easeOf = (s: Step) => {
      const eased = s.ease ?? "outQuad";
      return ENGINE_EASES.has(eased) ? eased : "outQuad";
    };
    b.scenes.forEach((scene, si) => {
      const sec = root.querySelector<HTMLElement>(`[data-scene="${scene.scene_id}"]`);
      if (!sec) return;
      if (si === 0) {
        // First scene: legacy instant intro, never touched.
        tl.set(sec, { opacity: 0 }, offset);
        tl.set(sec, { opacity: 1 }, offset + 1);
      } else {
        // ADR-040/041: the outgoing scene's transition_out drives the boundary,
        // with its own transition_ms length. transition_in is legacy metadata.
        const prev = root.querySelector<HTMLElement>(`[data-scene="${b.scenes[si - 1].scene_id}"]`);
        const trans = (b.scenes[si - 1] as Scene).transition_out ?? "cut";
        const T = offset;
        // transition_ms is contract-bound to 200–1000; scenes are >= 1000 ms,
        // so T - D never goes negative.
        const D = (b.scenes[si - 1] as Scene).transition_ms ?? 400;
        if (trans === "dissolve" || trans === "zoom_blur") {
          if (prev) {
            tl.set(prev, { opacity: 1 }, T - D);
            addHold(prev, { opacity: [1, 0], duration: D, ease: "linear" }, T - D, D);
          }
          tl.set(sec, { opacity: 0, scale: trans === "zoom_blur" ? 1.12 : 1 }, T - D);
          addHold(
            sec,
            trans === "zoom_blur"
              ? { opacity: [0, 1], scale: [1.12, 1], duration: D, ease: "linear" }
              : { opacity: [0, 1], duration: D, ease: "linear" },
            T - D,
            D,
          );
        } else if (trans === "fade") {
          if (prev) {
            tl.set(prev, { opacity: 1 }, T - D);
            addHold(prev, { opacity: [1, 0], duration: D, ease: "linear" }, T - D, D);
          }
          tl.set(sec, { opacity: 0 }, T);
          addHold(sec, { opacity: [0, 1], duration: D, ease: "linear" }, T, D);
        } else if (trans === "wipe") {
          tl.set(sec, { clipPath: "inset(0 100% 0 0)", opacity: 1 }, T - D);
          addHold(
            sec,
            {
              clipPath: ["inset(0 100% 0 0)", "inset(0 0% 0 0)"],
              duration: D,
              ease: "linear",
            },
            T - D,
            D,
          );
          if (prev) tl.set(prev, { opacity: 0 }, T);
        } else {
          // cut: legacy instant behavior preserved exactly.
          tl.set(sec, { opacity: 0 }, T);
          tl.set(sec, { opacity: 1 }, T + 1);
          if (prev) tl.set(prev, { opacity: 0 }, T);
        }
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
          case "mask_reveal": {
            // Cinematic clip-path wipe. The element must already exist
            // (title/line/conclusion); the wipe is the animation.
            const n = el(step.target);
            if (n) {
              tl.set(n, { clipPath: "inset(-3% 102% -3% 0%)", opacity: 1 }, at);
              addHold(
                n,
                {
                  clipPath: ["inset(-3% 102% -3% 0%)", "inset(-3% -2% -3% 0%)"],
                  duration: d,
                  ease,
                },
                at,
                d,
              );
            }
            break;
          }
          case "elastic_pop": {
            // Scale pop; pair with an elastic ease for the bounce.
            const n = el(step.target);
            if (n) {
              tl.set(n, { scale: 0.6, opacity: 0 }, at);
              addHold(n, { scale: [0.6, 1], opacity: [0, 1], duration: d, ease }, at, d);
            }
            break;
          }
          case "shake": {
            // Impact shake; amplitude in px, decaying oscillation.
            const n = el(step.target);
            if (n) {
              const raw = Number(step.params?.amplitude ?? 12);
              const amp = Number.isFinite(raw) ? Math.min(24, Math.max(4, raw)) : 12;
              addHold(
                n,
                { x: [0, -amp, amp, -amp * 0.6, amp * 0.6, 0], duration: d, ease: "outQuad" },
                at,
                d,
              );
            }
            break;
          }
          case "gradient_shift": {
            // Hue drift on the backdrop layer. Best on programmatic
            // gradients; use small angles over generated plates.
            const bgm = sec.querySelector<HTMLElement>('[data-layer="bg"]');
            if (bgm) {
              const raw = Number(step.params?.degrees ?? 50);
              const deg = Number.isFinite(raw) ? Math.min(120, Math.max(-120, raw)) : 50;
              tl.set(bgm, { filter: "hue-rotate(0deg)" }, at);
              addHold(
                bgm,
                { filter: ["hue-rotate(0deg)", `hue-rotate(${deg}deg)`], duration: d, ease: "linear" },
                at,
                d,
              );
            }
            break;
          }
          case "tracking": {
            // Letterspacing settle; spread in em units.
            const n = el(step.target);
            if (n) {
              const raw = Number(step.params?.spread ?? 0.35);
              const spread = Number.isFinite(raw) ? Math.min(0.6, Math.max(0.1, raw)) : 0.35;
              tl.set(n, { opacity: 0, letterSpacing: `${spread}em` }, at);
              addHold(
                n,
                { opacity: [0, 1], letterSpacing: [`${spread}em`, "0em"], duration: d, ease },
                at,
                d,
              );
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
    // ADR-040 multitrack layer 1: global overlays above the scenes.
    for (const overlay of b.overlays ?? []) {
      const node = root.querySelector<HTMLElement>(`[data-overlay="${overlay.overlay_id}"]`);
      if (!node) continue;
      const dur = Math.max(1, overlay.end_ms - overlay.start_ms);
      const fade = Math.min(300, Math.floor(dur / 2));
      tl.set(node, { opacity: 0 }, 0);
      addHold(node, { opacity: [0, 1], duration: fade, ease: "linear" }, overlay.start_ms, fade);
      addHold(node, { opacity: [1, 0], duration: fade, ease: "linear" }, overlay.end_ms - fade, fade);
    }
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
    <div
      id="idea-stage"
      ref={stageRef}
      style={{
        position: "relative",
        width: W,
        height: H,
        flexShrink: 0,
        overflow: "hidden",
        background: "#05060f",
      }}
    >
      {board.scenes.map((scene) => {
        const used = new Set(scene.animation_sequence.map((s) => s.target));
        return (
        <section key={scene.scene_id} data-scene={scene.scene_id} style={{ position: "absolute", inset: 0, opacity: 0 }}>
          {(() => {
            const src = assetForScene(scene.scene_id);
            if (src) {
              // eslint-disable-next-line @next/next/no-img-element
              return <img data-layer="bg" src={src} alt="" style={{ position: "absolute", inset: 0, width: "100%", height: "100%", objectFit: "cover", filter: scene.backdrop_hue_deg != null ? `hue-rotate(${scene.backdrop_hue_deg}deg)` : undefined }} />;
            }
            // Programmatic backdrop: deterministic gradient, no raster needed.
            const hue = scene.backdrop_hue_deg != null ? scene.backdrop_hue_deg : sceneHue(scene.scene_id);
            return <div data-layer="bg" style={{ position: "absolute", inset: 0, background: `linear-gradient(160deg, hsl(${hue},42%,10%), hsl(${(hue + 50) % 360},48%,20%))` }} />;
          })()}
          {(() => {
            // Multiplane foreground: bottom-anchored band drifting against
            // the backdrop via parallax (layers move at different speeds).
            const fsrc = fgAssetForScene(scene.scene_id);
            if (!fsrc) return null;
            // eslint-disable-next-line @next/next/no-img-element
            return <img data-layer="fg" src={fsrc} alt="" style={{ position: "absolute", left: 0, right: 0, bottom: 0, height: "62%", width: "100%", objectFit: "cover", objectPosition: "center bottom" }} />;
          })()}
          {used.has("grid") && (
            <div
              data-el="grid"
              style={{
                position: "absolute",
                inset: 0,
                opacity: 0.18,
                backgroundImage:
                  "linear-gradient(to right, rgba(255,255,255,.35) 1px, transparent 1px), linear-gradient(to bottom, rgba(255,255,255,.35) 1px, transparent 1px)",
                backgroundSize: "72px 72px",
                maskImage: "radial-gradient(circle at 50% 55%, #000 20%, transparent 78%)",
                WebkitMaskImage: "radial-gradient(circle at 50% 55%, #000 20%, transparent 78%)",
              }}
            />
          )}
          {used.has("orb") && (
            <div
              data-el="orb"
              style={{
                position: "absolute",
                left: "50%",
                top: "46%",
                width: 190,
                height: 190,
                marginLeft: -95,
                marginTop: -95,
                borderRadius: "50%",
                background: "radial-gradient(circle at 35% 30%, #ffe1bd, #ff7659 48%, #7a2d1d 100%)",
                boxShadow: "0 0 100px rgba(255,118,89,.45)",
              }}
            />
          )}
          {used.has("particles") && <div data-el="particles" style={{ position: "absolute", left: "50%", top: "52%", width: 0, height: 0 }} />}
          {used.has("asteroid") && <div data-el="asteroid" style={{ position: "absolute", left: 0, top: 0, width: 90, height: 90, borderRadius: "50%", background: "radial-gradient(circle at 35% 35%, #6b6259, #241f1b 70%)", boxShadow: "0 0 40px rgba(255,150,60,.35)" }} />}
          {used.has("plasma_trail") && <div data-el="plasma_trail" style={{ position: "absolute", left: "50%", top: "55%", width: 0, height: 0 }} />}
          {used.has("shockwave") && <div data-el="shockwave" style={{ position: "absolute", left: "50%", top: "62%", transform: "translate(-50%,-50%)", borderRadius: "50%", border: "6px solid rgba(255,200,120,.9)" }} />}
          {used.has("flash") && <div data-el="flash" style={{ position: "absolute", inset: 0, background: "#fff", opacity: 0 }} />}
          {used.has("divider") && (
          <svg data-el="divider" width={W} height={H} style={{ position: "absolute", inset: 0 }}>
            <path d={`M60,${Math.round(H * 0.86)} L${W - 60},${Math.round(H * 0.86)}`} stroke="#ffb36b" strokeWidth="4" fill="none" />
          </svg>
          )}
          {(() => {
            const style = scene.text_style;
            const topPct = style?.valign === "middle" ? 0.34 : style?.valign === "lower" ? 0.55 : 0.1;
            const fontFamily =
              style?.family === "serif"
                ? "Georgia, 'Times New Roman', serif"
                : style?.family === "mono"
                  ? "ui-monospace, SFMono-Regular, Menlo, monospace"
                  : "var(--font-manrope), ui-sans-serif, system-ui, sans-serif";
            return (
          <div style={{ position: "absolute", left: 40, right: 40, top: Math.round(H * topPct), textAlign: style?.align ?? "left" }}>
            {scene.on_screen_text.map((t, i) => {
              const elId = i === 0 ? "title" : `line${i}`;
              const animated = scene.animation_sequence.some(
                (s) => s.primitive === "kinetic_typography" && s.target === elId
              );
              // Auto-fit: long lines shrink so layout QA never clips them.
              // Title is the hook (big), lines are support (compact).
              const baseSize =
                i === 0
                  ? t.length > 30
                    ? 38
                    : t.length > 20
                      ? 46
                      : 54
                  : t.length > 44
                    ? 22
                    : t.length > 32
                      ? 26
                      : 32;
              const size = Math.round(baseSize * (style?.size_scale ?? 1));
              return (
              <div key={i} data-el={elId} style={{ color: style?.color ?? "#fff", fontFamily, fontWeight: style?.weight ?? 800, fontSize: size, lineHeight: i === 0 ? 1.06 : 1.25, letterSpacing: `${(style?.letter_spacing_em ?? 0) + (i === 0 ? -0.015 : 0)}em`, textShadow: "0 2px 18px rgba(0,0,0,.8)", marginBottom: i === 0 ? 16 : 10 }}>
                {kinetic(t, animated)}
              </div>
              );
            })}
          </div>
            );
          })()}
          {used.has("conclusion") && (
          <div data-el="conclusion" style={{ position: "absolute", left: 40, right: 40, bottom: 220, color: "#ffd9a8", fontFamily: "var(--font-manrope), ui-sans-serif, system-ui, sans-serif", fontSize: 28, opacity: 0 }}>
            {kinetic(scene.on_screen_text[scene.on_screen_text.length - 1] ?? "", scene.animation_sequence.some((s) => s.primitive === "kinetic_typography" && s.target === "conclusion"))}
          </div>
          )}
          {used.has("counter") && <div data-el="counter" style={{ position: "absolute", left: 40, top: 560, color: "#fff", fontFamily: "var(--font-manrope), ui-sans-serif, system-ui, sans-serif", fontWeight: 800, fontSize: 72 }}>0 m</div>}
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
      {/* ADR-040/041 multitrack layers: global overlays above every scene. */}
      {(board.overlays ?? []).length > 0 && (
        <div data-layer="overlays" style={{ position: "absolute", inset: 0, pointerEvents: "none", zIndex: 30 }}>
          {(board.overlays ?? []).map((overlay) => {
            const style = overlay.style;
            if (overlay.kind === "image" && overlay.asset_id) {
              const src = assetUrls ? assetUrls[overlay.asset_id] : undefined;
              if (!src && !assetBasePath) return null;
              return (
                // eslint-disable-next-line @next/next/no-img-element
                <img
                  key={overlay.overlay_id}
                  data-overlay={overlay.overlay_id}
                  src={src ?? `${assetBasePath}/${overlay.asset_id}.png`}
                  alt=""
                  style={{ position: "absolute", inset: 0, width: "100%", height: "100%", objectFit: "cover", opacity: 0 }}
                />
              );
            }
            const valign = style?.valign ?? "lower";
            const fontFamily =
              style?.family === "serif"
                ? "Georgia, 'Times New Roman', serif"
                : style?.family === "mono"
                  ? "ui-monospace, SFMono-Regular, Menlo, monospace"
                  : "var(--font-manrope), ui-sans-serif, system-ui, sans-serif";
            return (
              <div
                key={overlay.overlay_id}
                data-overlay={overlay.overlay_id}
                style={{
                  position: "absolute",
                  left: 40,
                  right: 40,
                  top: valign === "top" ? Math.round(H * 0.16) : valign === "middle" ? Math.round(H * 0.42) : undefined,
                  bottom: valign === "lower" ? Math.round(H * 0.12) : undefined,
                  textAlign: style?.align ?? "center",
                  color: style?.color ?? "#fff",
                  fontFamily,
                  fontWeight: style?.weight ?? 800,
                  fontSize: Math.round(30 * (style?.size_scale ?? 1)),
                  lineHeight: 1.25,
                  letterSpacing: `${style?.letter_spacing_em ?? 0}em`,
                  textShadow: "0 2px 14px rgba(0,0,0,.85)",
                  opacity: 0,
                }}
              >
                {overlay.text}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
});

export default SceneRenderer;
