"use client";

/* Headless capture surface for one idea render.
 *
 * This page is NOT a product screen: it exists so the worker's Playwright
 * session can mount the shared SceneRenderer with a validated manifest from
 * the API. It accepts only the idea id in the route, never a board, path or
 * URL from the query string, and sets document.title="READY" only after the
 * engine, fonts and images are ready to paint.
 */

import { useParams } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import SceneRenderer, { type Board, type SceneRendererHandle } from "@/components/SceneRenderer";
import { API_BASE } from "@/lib/api";

type Manifest = {
  idea_id: string;
  storyboard: Board;
  asset_urls: Record<string, string>;
  width: number;
  height: number;
  fps: number;
  duration_seconds: number;
  frame_count: number;
};

type IdeaWindow = {
  __idea?: {
    seek: (ms: number) => void;
    durationMs: number;
    debug: () => { currentTime: number | undefined; duration: number | undefined };
  };
};

export default function RenderSurfacePage() {
  const params = useParams<{ ideaId: string | string[] }>();
  const ideaId = Array.isArray(params?.ideaId) ? params.ideaId[0] : params?.ideaId;
  const [manifest, setManifest] = useState<Manifest | null>(null);
  const [error, setError] = useState<string | null>(null);
  const rendererRef = useRef<SceneRendererHandle>(null);

  useEffect(() => {
    if (!ideaId) return;
    let cancelled = false;
    fetch(`${API_BASE}/api/ideas/${encodeURIComponent(ideaId)}/render-manifest`, {
      cache: "no-store",
    })
      .then(async (response) => {
        if (!response.ok) {
          const body = (await response.json().catch(() => null)) as
            | { error?: { message?: string } }
            | null;
          throw new Error(body?.error?.message ?? `HTTP ${response.status}`);
        }
        return (await response.json()) as Manifest;
      })
      .then((data) => {
        if (!cancelled) setManifest(data);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setError(err instanceof Error ? err.message : "Falha ao carregar o manifesto.");
        document.title = "ERROR";
      });
    return () => {
      cancelled = true;
    };
  }, [ideaId]);

  useEffect(() => {
    if (!manifest) return;
    const api = {
      seek: (ms: number) => rendererRef.current?.seek(ms),
      durationMs: manifest.duration_seconds * 1000,
      debug: () => rendererRef.current?.debug() ?? { currentTime: undefined, duration: undefined },
    };
    (window as unknown as IdeaWindow).__idea = api;
    return () => {
      delete (window as unknown as IdeaWindow).__idea;
    };
  }, [manifest]);

  if (!manifest) {
    return (
      <main
        style={{
          display: "grid",
          minHeight: "100vh",
          placeItems: "center",
          background: "#000",
          color: "#a79e8f",
          fontFamily: "var(--font-plex-mono), monospace",
          fontSize: 12,
          padding: 24,
          textAlign: "center",
        }}
      >
        {error ?? "A preparar a superfície de render…"}
      </main>
    );
  }

  return (
    <main
      style={{
        display: "flex",
        width: "100vw",
        height: "100vh",
        alignItems: "center",
        justifyContent: "center",
        overflow: "hidden",
        background: "#000",
      }}
    >
      <SceneRenderer
        ref={rendererRef}
        board={manifest.storyboard}
        assetUrls={manifest.asset_urls}
        width={manifest.width}
        height={manifest.height}
        onReady={() => {
          document.title = "READY";
        }}
      />
    </main>
  );
}
