"use client";

/* Clip text overlay layer — Fase 1 preview-only (ADR-045).
 * Absolute layer inside the Viewer format card. One anime.js timeline for
 * all texts, driven by video currentTime via seek(ms, true). Same hold
 * pattern as SceneRenderer so completed tweens stick under seek-only
 * rendering. Position (x/y) is CSS only, never animated — drag updates it
 * without rebuilding the timeline. Reduced-motion: render static at full
 * opacity when the user prefers it. */

import { useEffect, useRef, useState } from "react";
import { createTimeline } from "animejs";
import { styleFor, type ClipTextOverlay } from "@/lib/textOverlays";

interface Props {
  texts: ClipTextOverlay[];
  currentTime: number;
  selectedId: string | null;
  onSelect: (id: string | null) => void;
  onMove: (id: string, x: number, y: number) => void;
  onCommitText?: (id: string, text: string) => void;
}

export function ClipTextLayer({ texts, currentTime, selectedId, onSelect, onMove, onCommitText }: Props) {
  const rootRef = useRef<HTMLDivElement>(null);
  const tlRef = useRef<ReturnType<typeof createTimeline> | null>(null);
  const dragRef = useRef<{ id: string; startX: number; startY: number; origX: number; origY: number; moved: boolean } | null>(null);
  const sigRef = useRef("");
  // Click-to-select guard: pointerdown already selects the overlay, so the
  // click that follows the same press must keep (not toggle) the selection.
  // Clicking an already-selected overlay still deselects it.
  const selectedRef = useRef<string | null>(null);
  selectedRef.current = selectedId;
  const guardRef = useRef<string | null>(null);
  // Inline editing: double-click a selected overlay to type in place. The
  // draft commits through the same onCommitText path as Properties.
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editingDraft, setEditingDraft] = useState("");

  const visible = texts.filter((t) => t.text.trim().length > 0 || t.id === selectedId);

  // Build the timeline when identity/style/timing changes — not on drag.
  const sig = texts.map((t) => `${t.id}:${t.style}:${t.start.toFixed(3)}:${t.duration.toFixed(3)}:${t.text}`).join("|");
  useEffect(() => {
    if (sig === sigRef.current) return;
    sigRef.current = sig;
    const root = rootRef.current;
    if (!root) return;
    tlRef.current?.revert();
    const prefersReduced =
      typeof window !== "undefined" &&
      typeof window.matchMedia === "function" &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const tl = createTimeline({ autoplay: false, defaults: { ease: "outQuad" } });
    type TweenProps = { [k: string]: number | string | number[] | string[] };
    const hold = (target: object, props: TweenProps, at: number, d: number) => {
      const end: TweenProps = {};
      for (const [k, v] of Object.entries(props)) {
        if (["duration", "ease", "delay", "onUpdate", "onBegin", "onComplete"].includes(k)) continue;
        end[k] = Array.isArray(v) ? (v[v.length - 1] as number) : v;
      }
      tl.set(target, end, Math.max(0, at + d));
    };
    const addHold = (target: object, props: TweenProps, at: number, d: number) => {
      tl.add(target, props, Math.max(0, at));
      hold(target, props, Math.max(0, at), Math.max(1, d));
    };

    for (const t of texts) {
      const node = root.querySelector<HTMLElement>(`[data-cliptext="${t.id}"]`);
      if (!node) continue;
      const style = styleFor(t.style);
      const at = Math.round(t.start * 1000);
      const total = Math.max(300, Math.round(t.duration * 1000));
      const enter = Math.min(style.enterMs, Math.max(200, total - 120));
      const exitAt = at + Math.max(enter + 60, total - 260);
      if (prefersReduced) {
        tl.set(node, { opacity: 0 }, 0);
        tl.set(node, { opacity: 1 }, at);
        tl.set(node, { opacity: 0 }, at + total);
        continue;
      }
      switch (t.style) {
        case "rise": {
          tl.set(node, { opacity: 0, y: 24 }, at);
          addHold(node, { opacity: [0, 1], y: [24, 0], duration: enter, ease: style.ease }, at, enter);
          break;
        }
        case "reveal": {
          tl.set(node, { opacity: 1, clipPath: "inset(0 100% 0 0)" }, at);
          addHold(
            node,
            { clipPath: ["inset(0 100% 0 0)", "inset(0 0% 0 0)"], duration: enter, ease: style.ease },
            at,
            enter,
          );
          break;
        }
        case "pop": {
          tl.set(node, { opacity: 0, scale: 0.6 }, at);
          addHold(node, { opacity: [0, 1], scale: [0.6, 1], duration: enter, ease: style.ease }, at, enter);
          break;
        }
        case "kinetic": {
          const chars = Array.from(node.querySelectorAll<HTMLElement>(".kch"));
          if (chars.length === 0) {
            tl.set(node, { opacity: 0, y: 24 }, at);
            addHold(node, { opacity: [0, 1], y: [24, 0], duration: enter, ease: style.ease }, at, enter);
          } else {
            const each = Math.max(90, enter / Math.max(1, chars.length));
            chars.forEach((ch, i) => {
              const ct = at + i * 32;
              tl.set(ch, { opacity: 0, y: 26 }, ct);
              addHold(ch, { opacity: [0, 1], y: [26, 0], duration: each, ease: style.ease }, ct, each);
            });
            hold(node, { opacity: 1 }, at, Math.min(enter + chars.length * 32, total - 100));
          }
          break;
        }
        case "tracking": {
          tl.set(node, { opacity: 0, letterSpacing: "0.35em" }, at);
          addHold(
            node,
            { opacity: [0, 1], letterSpacing: ["0.35em", "0em"], duration: enter, ease: style.ease },
            at,
            enter,
          );
          break;
        }
        default:
          break;
      }
      // Shared outro: quick fade so the text never pops out.
      addHold(node, { opacity: [1, 0], duration: 240, ease: "linear" }, exitAt, 240);
      tl.set(node, { opacity: 0 }, 0);
    }
    tlRef.current = tl;
    tl.seek(Math.round(currentTime * 1000), true);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sig]);

  // Drive by video clock.
  useEffect(() => {
    tlRef.current?.seek(Math.round(currentTime * 1000), true);
  }, [currentTime]);

  function onPointerDown(id: string, x: number, y: number) {
    return (e: React.PointerEvent) => {
      e.stopPropagation();
      (e.currentTarget as HTMLElement).setPointerCapture?.(e.pointerId);
      dragRef.current = { id, startX: e.clientX, startY: e.clientY, origX: x, origY: y, moved: false };
      guardRef.current = selectedRef.current !== id ? id : null;
      onSelect(id);
    };
  }

  function onOverlayClick(t: ClipTextOverlay) {
    if (guardRef.current === t.id) {
      guardRef.current = null;
      return; // the pointerdown of this press already selected it
    }
    onSelect(selectedRef.current === t.id ? null : t.id);
  }

  function onPointerMove(e: React.PointerEvent) {
    const d = dragRef.current;
    const root = rootRef.current;
    if (!d || !root) return;
    const rect = root.getBoundingClientRect();
    if (rect.width <= 0 || rect.height <= 0) return;
    const dx = (e.clientX - d.startX) / rect.width;
    const dy = (e.clientY - d.startY) / rect.height;
    if (Math.abs(e.clientX - d.startX) + Math.abs(e.clientY - d.startY) > 4) d.moved = true;
    if (!d.moved) return;
    const nx = Math.min(0.92, Math.max(0.08, d.origX + dx));
    const ny = Math.min(0.9, Math.max(0.1, d.origY + dy));
    onMove(d.id, Math.round(nx * 1000) / 1000, Math.round(ny * 1000) / 1000);
  }

  function onPointerUp() {
    dragRef.current = null;
  }

  function commitEditing() {
    if (!editingId) return;
    const clean = editingDraft.trim().slice(0, 140);
    const id = editingId;
    setEditingId(null);
    if (clean.length > 0) onCommitText?.(id, clean);
  }

  if (visible.length === 0) return null;

  return (
    <div ref={rootRef} className="pointer-events-none absolute inset-0 z-10" aria-label="Textos sobre o vídeo">
      {visible.map((t) => {
        const selected = t.id === selectedId;
        const editing = t.id === editingId;
        const inWindow = currentTime + 0.001 >= t.start && currentTime <= t.start + t.duration + 0.05;
        return (
          <div
            key={t.id}
            data-cliptext={t.id}
            role="button"
            tabIndex={0}
            aria-label={`Texto ${t.text || "(sem texto)"} — arrasta para posicionar, duplo clique para editar`}
            title="Arrasta para posicionar · clica para editar em Propriedades · duplo clique edita aqui"
            onPointerDown={onPointerDown(t.id, t.x, t.y)}
            onPointerMove={onPointerMove}
            onPointerUp={onPointerUp}
            onPointerCancel={onPointerUp}
            onClick={(e) => {
              e.stopPropagation();
              if (editing) return;
              onOverlayClick(t);
            }}
            onDoubleClick={(e) => {
              e.stopPropagation();
              onSelect(t.id);
              setEditingId(t.id);
              setEditingDraft(t.text);
            }}
            onKeyDown={(e) => {
              if (editing) return;
              if (e.key === "Enter") {
                e.preventDefault();
                if (selected) {
                  setEditingId(t.id);
                  setEditingDraft(t.text);
                } else {
                  onSelect(t.id);
                }
              } else if (e.key === " ") {
                e.preventDefault();
                onSelect(selected ? null : t.id);
              }
            }}
            className={`pointer-events-auto absolute max-w-[86%] touch-none select-none rounded px-1 focus-visible:outline-2 focus-visible:outline-accent ${
              selected ? "outline-2 outline-accent" : ""
            }`}
            style={{
              left: `${t.x * 100}%`,
              top: `${t.y * 100}%`,
              transform: "translate(-50%, -50%)",
              opacity: inWindow ? undefined : 0,
              cursor: editing ? "text" : "grab",
            }}
          >
            {editing ? (
              <input
                autoFocus
                value={editingDraft}
                maxLength={140}
                onChange={(e) => setEditingDraft(e.target.value.slice(0, 140))}
                onBlur={commitEditing}
                onKeyDown={(e) => {
                  e.stopPropagation();
                  if (e.key === "Enter") commitEditing();
                  if (e.key === "Escape") setEditingId(null);
                }}
                onPointerDown={(e) => e.stopPropagation()}
                onClick={(e) => e.stopPropagation()}
                aria-label="Editar texto"
                className="w-48 rounded border border-accent bg-black/85 px-2 py-1 text-center text-white focus-visible:outline-2 focus-visible:outline-accent"
                style={{
                  fontFamily: "var(--font-manrope), ui-sans-serif, system-ui, sans-serif",
                  fontWeight: t.weight === "normal" ? 400 : 800,
                  fontSize: `calc(clamp(15px, 4.2cqw, 34px) * ${t.scale})`,
                }}
              />
            ) : (
            <span
              className={t.style === "kinetic" ? undefined : ""}
              style={{
                display: "inline-block",
                color: t.color || "#fff",
                fontFamily: "var(--font-manrope), ui-sans-serif, system-ui, sans-serif",
                fontWeight: t.weight === "normal" ? 400 : 800,
                fontSize: `calc(clamp(15px, 4.2cqw, 34px) * ${t.scale})`,
                lineHeight: 1.15,
                letterSpacing: "0em",
                textShadow: "0 2px 14px rgba(0,0,0,.85)",
                textAlign: "center",
                whiteSpace: "pre-wrap",
              }}
            >
              {t.style === "kinetic" ? (
                <>
                  {t.text.split("").map((ch, i) => (
                    <span key={i} className="kch" style={{ display: "inline-block" }}>
                      {ch === " " ? " " : ch}
                    </span>
                  ))}
                </>
              ) : (
                t.text
              )}
            </span>
            )}
          </div>
        );
      })}
    </div>
  );
}
