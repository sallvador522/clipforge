/**
 * Mock-mode voice fixtures (ADR-004). The backend's mock transcription provider
 * maps these IDs to deterministic transcripts. The UI always labels them as
 * simulated; real Meta transcription arrives at the Milestone 6 gate.
 */
export interface VoiceFixture {
  id: string;
  label: string;
  transcript: string;
}

export const VOICE_FIXTURES: VoiceFixture[] = [
  {
    id: "pt_blur_people_behind",
    label: "Blur the background",
    transcript: "Desfoca todas as pessoas atrás de mim.",
  },
  {
    id: "pt_replace_background_studio",
    label: "Replace with a studio",
    transcript: "Substitui o fundo por um estúdio profissional.",
  },
  {
    id: "pt_keep_me_sharp",
    label: "Keep me sharp, blur the rest",
    transcript: "Mantém-me nítido e desfoca o resto.",
  },
  {
    id: "pt_ambiguous_person",
    label: "Ambiguous reference (asks clarification)",
    transcript: "Desfoca ele, por favor.",
  },
];
