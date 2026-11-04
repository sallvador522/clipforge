"use client";

import { useEffect, useRef, useState } from "react";

/* Right-column tab switcher (organisation borrowed from pro NLE sidebars):
 * one tab for the contextual inspector, one for the Muse chat. Badges mark
 * where attention is needed; approval states auto-open Propriedades once
 * per state change (never yank the tab while the user is typing — the key
 * includes the state, so repeats don't re-switch). Panes stay mounted so a
 * recording or draft survives switching.
 */

interface Props {
  switchTo: "props" | "muse" | null;
  switchKey: string | null;
  /** Switch to Propriedades when this key changes (e.g. a new asset click). */
  revealKey?: string | null;
  propsBadge: boolean;
  museBadge: boolean;
  properties: React.ReactNode;
  muse: React.ReactNode;
}

function TabButton({
  active, badge, label, onClick, dotTitle,
}: {
  active: boolean;
  badge: boolean;
  label: string;
  onClick: () => void;
  dotTitle: string;
}) {
  return (
    <button
      type="button"
      role="tab"
      aria-selected={active}
      onClick={onClick}
      className={`relative flex h-full flex-1 items-center justify-center gap-1.5 text-[12px] transition-colors focus-visible:outline-2 focus-visible:outline-accent ${
        active ? "font-semibold text-foreground" : "text-muted hover:text-foreground"
      }`}
    >
      {label}
      {badge && (
        <span className="h-1.5 w-1.5 rounded-full bg-accent" aria-hidden title={dotTitle} />
      )}
      {active && <span className="absolute inset-x-6 bottom-0 h-0.5 rounded-full bg-accent" aria-hidden />}
    </button>
  );
}

export function RightPanel({ switchTo, switchKey, revealKey, propsBadge, museBadge, properties, muse }: Props) {
  const [tab, setTab] = useState<"props" | "muse">("muse");
  const lastSwitch = useRef<string | null>(null);
  const lastReveal = useRef<string | null>(null);

  useEffect(() => {
    if (!switchTo || !switchKey) return;
    const key = `${switchKey}:${switchTo}`;
    if (lastSwitch.current === key) return;
    lastSwitch.current = key;
    setTab(switchTo);
  }, [switchTo, switchKey]);

  useEffect(() => {
    if (!revealKey || lastReveal.current === revealKey) return;
    lastReveal.current = revealKey;
    setTab("props");
  }, [revealKey]);

  return (
    <section aria-label="Painel lateral" className="flex min-h-0 flex-1 flex-col">
      <div className="flex h-11 shrink-0 items-stretch border-b border-border px-1" role="tablist" aria-label="Propriedades ou Muse">
        <TabButton active={tab === "props"} badge={propsBadge} label="Propriedades" dotTitle="Há algo para rever" onClick={() => setTab("props")} />
        <TabButton active={tab === "muse"} badge={museBadge} label="Muse" dotTitle="O Muse precisa da tua atenção" onClick={() => setTab("muse")} />
      </div>
      <div className={`min-h-0 flex-1 flex-col ${tab === "props" ? "flex" : "hidden"}`} role="tabpanel" aria-label="Propriedades">
        {properties}
      </div>
      <div className={`min-h-0 flex-1 flex-col ${tab === "muse" ? "flex" : "hidden"}`} role="tabpanel" aria-label="Muse">
        {muse}
      </div>
    </section>
  );
}
