import type { JobResponse, JobResultData } from "./types";

export const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export class ApiClientError extends Error {
  code: string;
  status: number;
  constructor(status: number, code: string, message: string) {
    super(message);
    this.status = status;
    this.code = code;
  }
}

async function parseError(response: Response): Promise<ApiClientError> {
  try {
    const body = await response.json();
    if (body?.error?.code) return new ApiClientError(response.status, body.error.code, body.error.message);
  } catch {
    /* fall through to generic */
  }
  return new ApiClientError(response.status, "http_error", `Request failed (${response.status}).`);
}

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, {
      ...init,
      headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
    });
  } catch {
    throw new ApiClientError(0, "api_unreachable", `Cannot reach the ClipForge API at ${API_BASE}. Is the backend running?`);
  }
  if (!response.ok) throw await parseError(response);
  return (await response.json()) as T;
}

/** Real upload with real progress events (XMLHttpRequest; fetch cannot report upload progress). */
export function uploadVideo(file: File, onProgress: (percent: number) => void): Promise<JobResponse> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `${API_BASE}/api/uploads`);
    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable) onProgress(Math.round((event.loaded / event.total) * 100));
    };
    xhr.onerror = () =>
      reject(new ApiClientError(0, "api_unreachable", `Cannot reach the ClipForge API at ${API_BASE}. Is the backend running?`));
    xhr.onload = () => {
      try {
        const body = JSON.parse(xhr.responseText);
        if (xhr.status >= 200 && xhr.status < 300) resolve(body as JobResponse);
        else reject(new ApiClientError(xhr.status, body?.error?.code ?? "http_error", body?.error?.message ?? `Upload failed (${xhr.status}).`));
      } catch {
        reject(new ApiClientError(xhr.status, "bad_response", "The API returned an unreadable response."));
      }
    };
    const form = new FormData();
    form.append("file", file);
    xhr.send(form);
  });
}

export function submitVoice(jobId: string, audioFixtureId: string): Promise<JobResponse> {
  return requestJson<JobResponse>(`/api/jobs/${jobId}/voice`, {
    method: "POST",
    body: JSON.stringify({ audio_fixture_id: audioFixtureId }),
  });
}

export function getJob(jobId: string): Promise<JobResponse> {
  return requestJson<JobResponse>(`/api/jobs/${jobId}`);
}

export function getResult(jobId: string): Promise<JobResultData> {
  return requestJson<JobResultData>(`/api/jobs/${jobId}/result`);
}

export function downloadUrl(jobId: string): string {
  return `${API_BASE}/api/jobs/${jobId}/download`;
}

export async function checkHealth(): Promise<{ status: string; ai_mode: string }> {
  return requestJson("/health");
}
