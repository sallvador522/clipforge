"use client";

import { MotionConfig } from "motion/react";

/** One reduced-motion policy for the whole studio (Motion skill guidance). */
export function MotionProvider({ children }: { children: React.ReactNode }) {
  return <MotionConfig reducedMotion="user">{children}</MotionConfig>;
}
