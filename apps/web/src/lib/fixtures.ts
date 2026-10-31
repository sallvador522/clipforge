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

/**
 * Deterministic text→fixture matching for the typed-instruction alternative.
 * Mirrors the mock planner's keyword mapping; unmatched text is reported
 * honestly as unrecognised instead of being silently reinterpreted.
 */
export function matchFixtureByText(text: string): VoiceFixture | null {
  const t = text.toLowerCase();
  if (/\bele\b/.test(t) || t.includes("him") || t.includes("that person")) return VOICE_FIXTURES[3];
  if (t.includes("fundo") || t.includes("background") || t.includes("estúdio") || t.includes("estudio") || t.includes("studio")) {
    return t.includes("substitu") || t.includes("replace") || t.includes("studio") || t.includes("estúd")
      ? VOICE_FIXTURES[1]
      : VOICE_FIXTURES[0];
  }
  if (t.includes("nítid") || t.includes("nitid") || t.includes("sharp")) return VOICE_FIXTURES[2];
  if (t.includes("desfoc") || t.includes("blur")) return VOICE_FIXTURES[0];
  return null;
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
