/** Types mirroring the idea-to-video API payloads. Do not invent fields. */

export type IdeaStatusValue =
  | "queued"
  | "processing"
  | "awaiting_approval"
  | "completed"
  | "failed"
  | "rejected";

export type IdeaStylePreset = "cinematic" | "documentary" | "product" | "bold";

export interface IdeaOptionsData {
  duration_seconds: number;
  aspect_ratio: "9:16" | "16:9";
  fps: number;
  style_preset: IdeaStylePreset;
  use_generated_images: boolean;
  language: "pt-PT" | "pt-BR" | "en";
}

export interface CostEstimateData {
  storyboard_usd: number;
  images_usd: number;
  transcription_usd: number;
  total_usd: number;
  cap_usd: number;
  image_count: number;
}

export interface IdeaApprovalData {
  scope: "storyboard" | "assets";
  approved_usd: number;
  approved_at: string;
  provider_modes: Record<string, string>;
  brief_hash: string;
  asset_ids: string[];
  prompt_hashes: Record<string, string>;
}

export interface IdeaAssetData {
  asset_id: string;
  scene_ids: string[];
  prompt: string;
  orientation: "portrait" | "landscape";
  role: "background" | "foreground";
  status: "planned" | "approved" | "generating" | "generated" | "failed" | "skipped";
  url: string | null;
  is_mock: boolean;
  width: number | null;
  height: number | null;
  cost_usd: number;
  error: string | null;
}

export interface IdeaRenderData {
  version: number;
  url: string;
  sha256: string;
  width: number;
  height: number;
  fps: number;
  frame_count: number;
  duration_seconds: number;
  qa: Record<string, unknown>;
  created_at: string;
}

export interface IdeaProgressData {
  stage: string;
  current: number;
  total: number;
  updated_at: string;
}

export interface IdeaHistoryEntry {
  status: IdeaStatusValue;
  stage: string;
  at: string;
  note: string | null;
}

export interface StoryboardStep {
  primitive: string;
  target: string;
  start_ms: number;
  duration_ms: number;
  params?: Record<string, number | string | boolean>;
  ease?: string;
}

export interface TextStyleData {
  family: "sans" | "serif" | "mono";
  weight: number;
  size_scale: number;
  color: string;
  align: "left" | "center" | "right";
  valign: "top" | "middle" | "lower";
  letter_spacing_em: number;
}

export interface StoryboardScene {
  scene_id: string;
  duration_ms: number;
  narrative_purpose: string;
  visual_description: string;
  image_generation_prompt: string;
  on_screen_text: string[];
  text_style?: TextStyleData;
  backdrop_hue_deg?: number | null;
  animation_sequence: StoryboardStep[];
  transition_in: string;
  transition_out: string;
  transition_ms?: number;
  scientific_claims: string[];
}

export interface OverlayData {
  overlay_id: string;
  kind?: "text" | "image";
  text: string;
  asset_id?: string | null;
  start_ms: number;
  end_ms: number;
  style?: TextStyleData;
}

export interface StoryboardPatchOperation {
  op: string;
  scene_id?: string;
  [key: string]: unknown;
}

export interface StoryboardPatchData {
  instruction: string;
  outcome: "apply" | "clarification";
  summary: string;
  clarification_question: string | null;
  operations: StoryboardPatchOperation[];
}

export interface StoryboardData {
  schema_version: string;
  project_title: string;
  user_request: string;
  target_audience: string;
  tone: string;
  duration_seconds: number;
  aspect_ratio: "9:16" | "16:9" | "1:1";
  output_fps: number;
  resolution: string;
  visual_style_bible: string;
  scientific_assumptions: string[];
  narration_script: string;
  scenes: StoryboardScene[];
  asset_plan: {
    asset_id: string;
    scene_ids: string[];
    description: string;
    orientation: "portrait" | "landscape";
    role?: "background" | "foreground";
    style_tags: string[];
  }[];
  source_references: string[];
  music_and_sound_cues: string[];
  overlays?: OverlayData[];
}

export interface IdeaPayload {
  idea_id: string;
  project_id: string | null;
  status: IdeaStatusValue;
  stage: string;
  brief: string;
  options: IdeaOptionsData;
  estimate: CostEstimateData | null;
  storyboard: StoryboardData | null;
  storyboard_hash: string | null;
  pending_patch: StoryboardPatchData | null;
  pending_clarification_question: string | null;
  approvals: IdeaApprovalData[];
  assets: IdeaAssetData[];
  render: IdeaRenderData | null;
  versions: Record<string, unknown>[];
  spent_usd: number;
  error: { code: string; message: string } | null;
  progress: IdeaProgressData | null;
  modes: { director: string; image: string; effort: string };
  cancel_requested: boolean;
  history: IdeaHistoryEntry[];
  created_at: string;
  updated_at: string;
  can_approve_storyboard: boolean;
  can_approve_assets: boolean;
  can_render: boolean;
  can_download: boolean;
  can_cancel: boolean;
}

export interface IdeaConfigData {
  modes: { director: string; image: string; effort: string };
  transcribe_mode: "mock" | "live";
  prices: { storyboard_usd: number; image_usd: number };
  cap_usd: number;
  defaults: IdeaOptionsData;
}

export interface IdeaListItem {
  idea_id: string;
  brief: string;
  status: IdeaStatusValue;
  stage: string;
  spent_usd: number;
  created_at: string;
  updated_at: string;
}
