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

export type JobStatusValue =
  | "queued"
  | "processing"
  | "awaiting_approval"
  | "awaiting_clarification"
  | "rejected"
  | "unsupported"
  | "completed"
  | "failed"
  | string;

export interface JobResponse {
  job_id: string;
  project_id: string | null;
  status: JobStatusValue;
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

export interface ProjectData {
  project_id: string;
  title: string;
  mode: string;
  asset_count: number;
  created_at: string;
  updated_at: string;
}

export type AssetKind = "video" | "audio" | "image" | "text" | "graphics";

export interface AssetData {
  asset_id: string;
  project_id: string;
  kind: AssetKind | string;
  original_filename: string;
  stored_filename: string;
  mime: string;
  size_bytes: number;
  sha256: string;
  provenance: string;
  created_at: string;
  width?: number | null;
  height?: number | null;
  duration_seconds?: number | null;
  fps?: number | null;
  frame_count?: number | null;
  has_audio?: boolean | null;
  audio_codec?: string | null;
  audio_channels?: number | null;
  text_lines?: number | null;
  cue_count?: number | null;
  text_encoding?: string | null;
  sanitized?: boolean | null;
}

export interface TranscriptData {
  text: string;
  language: string;
  confidence: number | null;
  provider_name: string;
  is_mock: boolean;
  session_id: string | null;
  audio_duration_ms: number | null;
  transcribe_mode?: "mock" | "live";
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

export interface DirectorOperationData {
  operation_id: string;
  capability_id: string;
  title: string;
  explanation: string;
  params: Record<string, unknown>;
  dependencies: string[];
  status: string;
  expected_output: string;
}

export interface DirectorSubjectData {
  strategy: string;
  description: string;
  is_ambiguous: boolean;
  clarification_question: string | null;
}

export interface DirectorPlanData {
  schema_version: string;
  request_id: string;
  raw_instruction: string;
  interpreted_intention: string;
  outcome: "plan_ready" | "needs_clarification" | "unsupported" | string;
  subject: DirectorSubjectData;
  target: { format: string; aspect_ratio: string; resolution: string; preserve_audio: boolean };
  operations: DirectorOperationData[];
  required_providers: string[];
  estimated_stages: string[];
  expected_results: string[];
  verification_requirements: Array<{ check: string; description: string }>;
  summary_explanation: string;
  explanations: string[];
  clarification_questions: string[];
  unsupported_capabilities: string[];
  approval_status: "not_required" | "required" | "approved" | "rejected" | string;
}

export interface PlanCapabilityData {
  capability_id: string;
  name: string;
  status: string;
  simulated: boolean;
  requires_approval: boolean;
  provider: string | null;
}

export interface SegmentationSubjectData {
  object_id: string;
  label: string;
  preview_url: string | null;
  first_frame: number | null;
  last_frame: number | null;
  frames_detected: number;
  confidence: number | null;
}

export interface SegmentationReviewData {
  provider: string;
  model: string | null;
  is_mock: boolean;
  status: string;
  frame_count: number;
  width: number;
  height: number;
  fps: number;
  diagnostics: string[];
  file_cleanup: string;
}

export interface SegmentationSubjectResultData {
  object_id: string;
  label: string;
  mask_manifest_path: string;
  preview_path: string | null;
  first_frame: number | null;
  last_frame: number | null;
  frames_detected: number;
  confidence: number | null;
}

export interface PlanReviewData {
  job_id: string;
  status: JobStatusValue;
  stage: string;
  ready: boolean;
  plan: DirectorPlanData | null;
  legacy_plan: PlanData | null;
  capabilities: PlanCapabilityData[];
  requires_approval: boolean;
  requires_clarification: boolean;
  clarification_question: string | null;
  clarification_count: number;
  render_status: string;
  error: { code: string; message: string } | null;
  subjects: SegmentationSubjectData[];
  segmentation: SegmentationReviewData | null;
  selected_subject_ids: string[];
  selection_required: boolean;
  no_subjects: boolean;
}

export interface JobResultData {
  transcript: TranscriptData | null;
  plan: PlanData | null;
  director_plan: DirectorPlanData | null;
  segmentation: {
    frame_count: number;
    width: number;
    height: number;
    fps: number;
    is_mock: boolean;
    provider_name: string;
    model: string | null;
    status: string;
    subjects: SegmentationSubjectResultData[];
    diagnostics: string[];
    file_cleanup: string;
  } | null;
  background: { asset_id: string; orientation: string; is_mock: boolean } | null;
  rendered: RenderedData | null;
  director_usage: Record<string, unknown> | null;
  director_request_id: string | null;
  requires_approval: boolean;
  requires_clarification: boolean;
  render_status: string;
}
