/** Client for the idea-to-video endpoints. Kept separate from the edit API. */

import { API_BASE, ApiClientError } from "./api";
import type {
  IdeaConfigData,
  IdeaListItem,
  IdeaOptionsData,
  IdeaPayload,
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
): Promise<IdeaPayload> {
  return ideaRequest<IdeaPayload>("/api/ideas", {
    method: "POST",
    body: JSON.stringify({ brief, options }),
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
