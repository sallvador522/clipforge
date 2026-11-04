/** Clip text overlays — ADR-047: real project data.
 *
 * Persisted on the job (PUT /api/jobs/{id}/texts), edited in the Studio
 * (preview selection/drag, Properties Inspector, timeline T1, Muse tools)
 * and burned into the Montar/Export MP4 by the worker's real OpenCV/PIL
 * composition. The export carries a fade + rise entrance; per-style
 * anime.js choreography stays richer in the preview — the mapping is
 * stated honestly in the UI.
 */

export type ClipTextStyleId = "rise" | "reveal" | "pop" | "kinetic" | "tracking";
export type ClipTextWeight = "normal" | "bold";

export interface ClipTextOverlay {
  id: string;
  text: string;
  style: ClipTextStyleId;
  /** Global seconds in the program. */
  start: number;
  duration: number;
  /** Normalized 0..1 position of the text box centre inside the format card. */
  x: number;
  y: number;
  /** Relative font scale 0.7..1.6. */
  scale: number;
  /** Hex colour, honoured by preview and export. */
  color: string;
  /** Font weight, honoured by preview and export. */
  weight: ClipTextWeight;
}

export interface ClipTextStyle {
  id: ClipTextStyleId;
  label: string;
  description: string;
  /** Anime.js ease (must be in ENGINE_EASES allowlist). */
  ease: string;
  /** Entrance length in ms. */
  enterMs: number;
  primitive: string;
}

export const CLIP_TEXT_STYLES: ClipTextStyle[] = [
  {
    id: "rise",
    label: "Fundido a subir",
    description: "Sobe 24px com fade · outQuad",
    ease: "outQuad",
    enterMs: 600,
    primitive: "slide",
  },
  {
    id: "reveal",
    label: "Revelação",
    description: "Máscara lateral · inOutQuad",
    ease: "inOutQuad",
    enterMs: 700,
    primitive: "mask_reveal",
  },
  {
    id: "pop",
    label: "Pop",
    description: "Escala 0.6→1 · outBack",
    ease: "outBack",
    enterMs: 500,
    primitive: "elastic_pop",
  },
  {
    id: "kinetic",
    label: "Cinético",
    description: "Letra a letra · outExpo",
    ease: "outExpo",
    enterMs: 800,
    primitive: "kinetic_typography",
  },
  {
    id: "tracking",
    label: "Tracking",
    description: "Espaçamento 0.35em→0 · outQuad",
    ease: "outQuad",
    enterMs: 800,
    primitive: "tracking",
  },
];

export const CLIP_TEXT_COLOURS: { hex: string; label: string }[] = [
  { hex: "#FFFFFF", label: "Branco" },
  { hex: "#FFD400", label: "Amarelo" },
  { hex: "#FF2D2D", label: "Vermelho" },
  { hex: "#2D9BFF", label: "Azul" },
  { hex: "#35D05A", label: "Verde" },
  { hex: "#FF8A00", label: "Laranja" },
  { hex: "#FF5FA2", label: "Rosa" },
  { hex: "#000000", label: "Preto" },
];

export function styleFor(id: ClipTextStyleId): ClipTextStyle {
  return CLIP_TEXT_STYLES.find((s) => s.id === id) ?? CLIP_TEXT_STYLES[0];
}

export function newClipTextId(): string {
  const rand = Math.floor(Math.random() * 0xffffffff)
    .toString(16)
    .padStart(8, "0");
  return `txt_${Date.now().toString(36)}${rand}`;
}

export function clampOverlay(
  overlay: ClipTextOverlay,
  programDuration: number,
): ClipTextOverlay {
  const prog = Math.max(0.5, programDuration || 0);
  const duration = Math.min(8, Math.max(0.5, overlay.duration || 2));
  const start = Math.min(Math.max(0, overlay.start || 0), Math.max(0, prog - 0.2));
  const color =
    typeof overlay.color === "string" && /^#[0-9a-fA-F]{6}$/.test(overlay.color)
      ? overlay.color.toUpperCase()
      : "#FFFFFF";
  const weight: ClipTextWeight = overlay.weight === "normal" ? "normal" : "bold";
  return {
    ...overlay,
    text: overlay.text.slice(0, 140),
    start: Math.round(start * 1000) / 1000,
    duration: Math.round(Math.min(duration, Math.max(0.3, prog - start)) * 1000) / 1000,
    x: Math.min(0.92, Math.max(0.08, overlay.x ?? 0.5)),
    y: Math.min(0.9, Math.max(0.1, overlay.y ?? 0.78)),
    scale: Math.min(1.6, Math.max(0.7, overlay.scale ?? 1)),
    color,
    weight,
  };
}

export function defaultOverlayAt(
  playhead: number,
  programDuration: number,
  style: ClipTextStyleId = "rise",
): ClipTextOverlay {
  const prog = Math.max(1, programDuration || 6);
  const start = Math.min(Math.max(0, playhead || 0), Math.max(0, prog - 2));
  return clampOverlay(
    {
      id: newClipTextId(),
      text: "O teu texto aqui",
      style,
      start,
      duration: Math.min(2.5, Math.max(1, prog - start)),
      x: 0.5,
      y: 0.78,
      scale: 1,
      color: "#FFFFFF",
      weight: "bold",
    },
    prog,
  );
}

export const TEXT_STORAGE_PREFIX = "clipforge.clipTexts.";

export function storageKeyFor(jobId: string | null): string {
  return `${TEXT_STORAGE_PREFIX}${jobId ?? "session"}`;
}
