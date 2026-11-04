/** Client for the idea-to-video endpoints. Kept separate from the edit API. */

import { API_BASE, ApiClientError } from "./api";
import type {
  IdeaConfigData,
  IdeaListItem,
  IdeaOptionsData,
  IdeaPayload,
  StoryboardData,
} from "./idea-types";

async function ideaRequest<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, {
      ...init,
      cache: "no-store",
      headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
    });
  } catch {
    throw new ApiClientError(
      0,
      "api_unreachable",
      `Não foi possível contactar a API em ${API_BASE}. O backend está a correr?`,
    );
  }
  if (!response.ok) {
    let code = "request_failed";
    let message = `HTTP ${response.status}`;
    try {
      const body = (await response.json()) as { error?: { code?: string; message?: string } };
      if (body.error?.code) code = body.error.code;
      if (body.error?.message) message = body.error.message;
    } catch {
      // Non-JSON error body: keep the HTTP status message.
    }
    throw new ApiClientError(response.status, code, message);
  }
  return (await response.json()) as T;
}

export function getIdeaConfig(): Promise<IdeaConfigData> {
  return ideaRequest<IdeaConfigData>("/api/ideas/config");
}

export function listIdeas(limit = 20): Promise<{ ideas: IdeaListItem[] }> {
  return ideaRequest<{ ideas: IdeaListItem[] }>(`/api/ideas?limit=${limit}`);
}

export function getIdea(ideaId: string): Promise<IdeaPayload> {
  return ideaRequest<IdeaPayload>(`/api/ideas/${encodeURIComponent(ideaId)}`);
}

export function createIdea(
  brief: string,
  options: IdeaOptionsData,
  projectId?: string | null,
): Promise<IdeaPayload> {
  return ideaRequest<IdeaPayload>("/api/ideas", {
    method: "POST",
    body: JSON.stringify({ brief, options, ...(projectId ? { project_id: projectId } : {}) }),
  });
}

export function approveStoryboard(ideaId: string, maxCostUsd: number): Promise<IdeaPayload> {
  return ideaRequest<IdeaPayload>(
    `/api/ideas/${encodeURIComponent(ideaId)}/approve-storyboard`,
    { method: "POST", body: JSON.stringify({ max_cost_usd: maxCostUsd }) },
  );
}

export function approveAssets(
  ideaId: string,
  body: { asset_ids: string[]; max_cost_usd: number; programmatic_only: boolean },
): Promise<IdeaPayload> {
  return ideaRequest<IdeaPayload>(
    `/api/ideas/${encodeURIComponent(ideaId)}/approve-assets`,
    { method: "POST", body: JSON.stringify(body) },
  );
}

export function rerenderIdea(ideaId: string, storyboardHash: string): Promise<IdeaPayload> {
  return ideaRequest<IdeaPayload>(`/api/ideas/${encodeURIComponent(ideaId)}/render`, {
    method: "POST",
    body: JSON.stringify({ storyboard_hash: storyboardHash }),
  });
}

export function patchStoryboard(
  ideaId: string,
  storyboard: StoryboardData,
  expectedHash: string,
): Promise<IdeaPayload> {
  return ideaRequest<IdeaPayload>(`/api/ideas/${encodeURIComponent(ideaId)}/storyboard`, {
    method: "PATCH",
    body: JSON.stringify({ storyboard, expected_hash: expectedHash }),
  });
}

/**
 * Deteção automática de duração no texto do pedido ("25 segundos", "30s",
 * "1 minuto"). Local e gratuita; o valor aplica-se à criação salvo override
 * manual nas pills. Limites do contrato: 5–60 s.
 */
const DURATION_MIN = 5;
const DURATION_RE = /(\d{1,3})\s*(minutos?|mins?|segundos?|segs?|[sm])\b/i;

export function detectDurationSeconds(text: string): number | null {
  const match = DURATION_RE.exec(text);
  if (!match) return null;
  const amount = Number.parseInt(match[1], 10);
  if (!Number.isFinite(amount)) return null;
  const unit = match[2].toLowerCase();
  const minutes = unit.startsWith("min") || unit === "m";
  const seconds = minutes ? amount * 60 : amount;
  if (seconds < DURATION_MIN) return null;
  // ADR-036: no fixed ceiling — the director's delivered duration wins.
  return seconds;
}

export function directIdea(
  ideaId: string,
  instruction: string,
  approvedCostUsd: number,
): Promise<IdeaPayload> {
  return ideaRequest<IdeaPayload>(`/api/ideas/${encodeURIComponent(ideaId)}/direct`, {
    method: "POST",
    body: JSON.stringify({ instruction, approved_cost_usd: approvedCostUsd }),
  });
}

export function applyRefinement(ideaId: string): Promise<IdeaPayload> {
  return ideaRequest<IdeaPayload>(`/api/ideas/${encodeURIComponent(ideaId)}/direct/apply`, {
    method: "POST",
  });
}

export function rejectRefinement(ideaId: string): Promise<IdeaPayload> {
  return ideaRequest<IdeaPayload>(`/api/ideas/${encodeURIComponent(ideaId)}/direct/reject`, {
    method: "POST",
  });
}

/**
 * Edição local 1-2 (texto + eliminação), sem chamadas de rede.
 * A eliminação redistribui a duração da cena removida pelas restantes
 * (proporcional, com acerto de arredondamento na última) para que a soma
 * continue a cobrir `duration_seconds`, e limpa o `asset_plan` de
 * referências órfãs. O servidor revalida tudo antes de guardar.
 */
export function updateSceneText(
  board: StoryboardData,
  sceneId: string,
  lines: string[],
): StoryboardData {
  return {
    ...board,
    scenes: board.scenes.map((scene) =>
      scene.scene_id === sceneId ? { ...scene, on_screen_text: [...lines] } : scene,
    ),
  };
}

export function deleteSceneFromBoard(board: StoryboardData, sceneId: string): StoryboardData {
  const target = board.scenes.find((scene) => scene.scene_id === sceneId);
  if (!target) return board;
  const remaining = board.scenes.filter((scene) => scene.scene_id !== sceneId);
  if (remaining.length === 0) return board;
  const removed = target.duration_ms;
  const total = remaining.reduce((sum, scene) => sum + scene.duration_ms, 0);
  let assigned = 0;
  const scenes = remaining.map((scene, index) => {
    const extra =
      index === remaining.length - 1
        ? removed - assigned
        : Math.round((removed * scene.duration_ms) / total);
    assigned += extra;
    const duration_ms = scene.duration_ms + extra;
    // Esticar a cena sem esticar os passos criava uma cauda estática que o
    // validador rejeita; os passos escalam proporcionalmente com a cena.
    const factor = duration_ms / scene.duration_ms;
    return {
      ...scene,
      duration_ms,
      animation_sequence: scene.animation_sequence.map((step) => {
        const start_ms = Math.round(step.start_ms * factor);
        const scaled = Math.max(100, Math.round(step.duration_ms * factor));
        return { ...step, start_ms, duration_ms: Math.min(scaled, duration_ms - start_ms) };
      }),
    };
  });
  return {
    ...board,
    scenes,
    asset_plan: board.asset_plan
      .map((spec) => ({
        ...spec,
        scene_ids: spec.scene_ids.filter((id) => id !== sceneId),
      }))
      .filter((spec) => spec.scene_ids.length > 0),
  };
}

export const SCENE_MIN_MS = 1000;
export const SCENE_MAX_MS = 15000;

/**
 * Escala os passos de uma cena para uma nova duração (mesma matemática da
 * eliminação): sem cauda estática, passos sempre dentro da cena.
 */
function scaleStepsToDuration(
  steps: StoryboardData["scenes"][number]["animation_sequence"],
  duration_ms: number,
  factor: number,
): StoryboardData["scenes"][number]["animation_sequence"] {
  return steps.map((step) => {
    const start_ms = Math.min(
      Math.round(step.start_ms * factor),
      Math.max(0, duration_ms - 100),
    );
    const scaled = Math.max(100, Math.round(step.duration_ms * factor));
    return { ...step, start_ms, duration_ms: Math.min(scaled, Math.max(100, duration_ms - start_ms)) };
  });
}

/**
 * Trim (ADR-039): muda a duração de uma cena (1000–15000 ms, com clamp) e
 * escala os passos proporcionalmente. A duração total deriva das cenas
 * (ADR-036); o re-render continua explícito. O servidor revalida tudo.
 */
export function trimSceneFromBoard(
  board: StoryboardData,
  sceneId: string,
  durationMs: number,
): StoryboardData {
  const target = board.scenes.find((scene) => scene.scene_id === sceneId);
  if (!target) return board;
  const clamped = Math.min(SCENE_MAX_MS, Math.max(SCENE_MIN_MS, Math.round(durationMs)));
  if (clamped === target.duration_ms) return board;
  const factor = clamped / target.duration_ms;
  return {
    ...board,
    scenes: board.scenes.map((scene) =>
      scene.scene_id === sceneId
        ? {
            ...scene,
            duration_ms: clamped,
            animation_sequence: scaleStepsToDuration(scene.animation_sequence, clamped, factor),
          }
        : scene,
    ),
  };
}

/** Próximo scene_id livre (`scene_N`). */
function nextSceneId(board: StoryboardData): string {
  let max = 0;
  for (const scene of board.scenes) {
    const match = /^scene_([1-9][0-9]*)$/.exec(scene.scene_id);
    if (match) max = Math.max(max, Number.parseInt(match[1], 10));
  }
  return `scene_${max + 1}`;
}

/**
 * Split (ADR-039): divide uma cena em duas na posição `atMs`.
 * Cada metade repete a animação da original comprimida à sua duração —
 * é a única forma válida (cada cena tem a sua própria linha de tempo a
 * começar em 0): garante cobertura de movimento e passos dentro da cena.
 * O texto é repetido nas duas metades (edita cada metade a seguir);
 * as plates são duplicadas (mesmo prompt → custo $0.00, preservadas).
 * Devolve `null` quando o corte é impossível (metades <1000 ms).
 * O servidor revalida tudo antes de guardar.
 */
export function splitSceneFromBoard(
  board: StoryboardData,
  sceneId: string,
  atMs: number,
): StoryboardData | null {
  const index = board.scenes.findIndex((scene) => scene.scene_id === sceneId);
  if (index < 0 || board.scenes.length >= 12) return null;
  const original = board.scenes[index];
  const cut = Math.round(atMs);
  const firstMs = cut;
  const secondMs = original.duration_ms - cut;
  if (firstMs < SCENE_MIN_MS || secondMs < SCENE_MIN_MS) return null;
  const newId = nextSceneId(board);
  const first = {
    ...original,
    duration_ms: firstMs,
    animation_sequence: scaleStepsToDuration(
      original.animation_sequence,
      firstMs,
      firstMs / original.duration_ms,
    ),
  };
  const second = {
    ...original,
    scene_id: newId,
    duration_ms: secondMs,
    animation_sequence: scaleStepsToDuration(
      original.animation_sequence,
      secondMs,
      secondMs / original.duration_ms,
    ),
  };
  const scenes = [...board.scenes];
  scenes.splice(index, 1, first, second);
  const existingIds = new Set(board.asset_plan.map((spec) => spec.asset_id));
  const asset_plan = board.asset_plan.flatMap((spec) => {
    if (!spec.scene_ids.includes(sceneId)) return [spec];
    const firstSpec = {
      ...spec,
      scene_ids: spec.scene_ids.flatMap((id) => (id === sceneId ? [sceneId] : [id])),
    };
    let copyId = `${spec.asset_id}_b`.slice(0, 40);
    let suffix = 2;
    while (existingIds.has(copyId)) copyId = `${spec.asset_id}_b${suffix++}`.slice(0, 40);
    existingIds.add(copyId);
    return [firstSpec, { ...spec, asset_id: copyId, scene_ids: [newId] }];
  });
  return { ...board, scenes, asset_plan };
}

/**
 * Reordenar (ADR-039): move a cena uma posição (arrasto na timeline ou
 * botões). Só a ordem muda — durações, passos e assets intactos.
 * Fora dos limites devolve o board inalterado.
 */
export function moveSceneInBoard(
  board: StoryboardData,
  sceneId: string,
  direction: -1 | 1,
): StoryboardData {
  const index = board.scenes.findIndex((scene) => scene.scene_id === sceneId);
  const other = index + direction;
  if (index < 0 || other < 0 || other >= board.scenes.length) return board;
  const scenes = [...board.scenes];
  [scenes[index], scenes[other]] = [scenes[other], scenes[index]];
  return { ...board, scenes };
}

/** Reordenar por arrasto: coloca `dragId` antes/depois de `targetId`. */
export function reorderSceneInBoard(
  board: StoryboardData,
  dragId: string,
  targetId: string,
  before: boolean,
): StoryboardData {
  if (dragId === targetId) return board;
  const scenes = board.scenes.filter((scene) => scene.scene_id !== dragId);
  const dragged = board.scenes.find((scene) => scene.scene_id === dragId);
  if (!dragged) return board;
  const targetIndex = scenes.findIndex((scene) => scene.scene_id === targetId);
  if (targetIndex < 0) return board;
  scenes.splice(before ? targetIndex : targetIndex + 1, 0, dragged);
  return { ...board, scenes };
}

export function cancelIdea(ideaId: string): Promise<IdeaPayload> {
  return ideaRequest<IdeaPayload>(`/api/ideas/${encodeURIComponent(ideaId)}/cancel`, {
    method: "POST",
  });
}

export function rejectIdea(ideaId: string): Promise<IdeaPayload> {
  return ideaRequest<IdeaPayload>(`/api/ideas/${encodeURIComponent(ideaId)}/reject`, {
    method: "POST",
  });
}

export function ideaDownloadUrl(idea: IdeaPayload): string | null {
  return idea.render?.url ?? null;
}
