"use client";

import type { ChatSettings } from "@/lib/types";

interface Props {
  settings: ChatSettings;
  busy: boolean;
  modelLabel: string | null;
  onToggleSidebar: () => void;
  onSettings: (patch: Partial<ChatSettings>) => void;
  onNew: () => void;
}

const THEME_ICON: Record<ChatSettings["theme"], string> = {
  light: "☀",
  dark: "☾",
  system: "◐",
};

export default function Topbar({
  settings,
  busy,
  modelLabel,
  onToggleSidebar,
  onSettings,
  onNew,
}: Props) {
  const cycleTheme = () => {
    const next =
      settings.theme === "light"
        ? "dark"
        : settings.theme === "dark"
          ? "system"
          : "light";
    onSettings({ theme: next });
  };

  return (
    <header
      className="sticky top-0 z-20 border-b backdrop-blur-md"
      style={{
        background: "color-mix(in srgb, var(--bg) 88%, transparent)",
        borderColor: "var(--border)",
      }}
    >
      <div className="flex h-[52px] items-center gap-2 px-3 sm:px-4">
        <button
          onClick={onToggleSidebar}
          className="rounded-lg px-2 py-1.5 text-[15px] leading-none hover:bg-black/5 dark:hover:bg-white/10 md:hidden"
          style={{ color: "var(--muted)" }}
          aria-label="Toggle sidebar"
        >
          ☰
        </button>

        <div
          className="flex min-w-0 items-center gap-2 rounded-full border px-3 py-1.5 text-xs"
          style={{
            borderColor: "var(--border)",
            background: "var(--surface)",
            color: "var(--muted)",
          }}
        >
          <span
            className="inline-block h-[6px] w-[6px] shrink-0 rounded-full"
            style={{
              background: busy ? "var(--warning)" : "var(--success)",
            }}
          />
          <span className="max-w-[220px] truncate font-medium">
            {busy ? "Generating…" : (modelLabel ?? "Hybrid retrieval + rerank")}
          </span>
        </div>

        <div className="flex-1" />

        <button
          onClick={cycleTheme}
          title={`Theme: ${settings.theme}`}
          className="grid h-8 w-8 place-items-center rounded-lg text-[14px] hover:bg-black/5 dark:hover:bg-white/10"
          style={{ color: "var(--muted)" }}
          aria-label="Cycle theme"
        >
          {THEME_ICON[settings.theme]}
        </button>

        <button
          onClick={onNew}
          title="New chat"
          className="grid h-8 w-8 place-items-center rounded-lg text-[17px] leading-none hover:bg-black/5 dark:hover:bg-white/10"
          style={{ color: "var(--muted)" }}
          aria-label="New chat"
        >
          +
        </button>
      </div>
    </header>
  );
}
