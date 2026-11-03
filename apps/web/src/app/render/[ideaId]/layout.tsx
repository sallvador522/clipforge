import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "ClipForge render surface",
  robots: { index: false, follow: false, nocache: true },
};

export default function RenderLayout({ children }: { children: React.ReactNode }) {
  return <div style={{ background: "#000", minHeight: "100vh" }}>{children}</div>;
}
