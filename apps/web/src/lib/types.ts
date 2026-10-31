/** Types mirroring docs/API_CONTRACTS.md exactly. Do not invent fields. */

export interface ApiErrorBody {
  error: { code: string; message: string };
}

export interface SourceInfo {
  width: number;
  height: number;
  fps: number;
  duration_seconds: number;
  frame_count: number;
  has_audio: boolean;
}

export interface JobResponse {
  job_id: string;
  status: "queued" | "processing" | "completed" | "failed" | string;
  stage: string;
  ready: boolean;
  original_filename: string;
  audio_fixture_id: string | null;
  source_info: SourceInfo;
  result: JobResultData | null;
  error: { code: string; message: string } | null;
  attempts: number;
  created_at: string;
  updated_at: string;
}

export interface TranscriptData {
  text: string;
  language: string;
  confidence: number;
  provider_name: string;
  is_mock: boolean;
}

export interface PlanData {
  plan_id: string;
  raw_transcript: string;
  language: string;
  intent: string;
  subject: { description: string; is_ambiguous: boolean; clarification_question: string | null };
  operations: Array<{ type: string; strength?: number; prompt?: string; asset_id?: string | null }>;
  preserve_audio: boolean;
  output_format: string;
}

export interface RenderedData {
  output_relative_path: string;
  mode: string;
  width: number;
  height: number;
  fps: number;
  frame_count: number;
  duration_seconds: number;
  file_size_bytes: number;
  has_audio: boolean;
}

export interface JobResultData {
  transcript: TranscriptData | null;
  plan: PlanData | null;
  segmentation: {
    frame_count: number;
    width: number;
    height: number;
    fps: number;
    is_mock: boolean;
  } | null;
  background: { asset_id: string; orientation: string; is_mock: boolean } | null;
  rendered: RenderedData | null;
  requires_clarification: boolean;
  render_status: string;
}
