"use client";

import type { ChatSession } from "@/lib/types";
import { BrandMark } from "./Brand";

interface Props {
  sessions: ChatSession[];
  activeId: string | null;
  open: boolean;
  health: "checking" | "ok" | "down";
  onSelect: (id: string) => void;
  onNew: () => void;
  onDelete: (id: string) => void;
  onClose: () => void;
  onRetryHealth: () => void;
}

function timeAgo(ts: number): string {
  const d = Date.now() - ts;
  const m = Math.floor(d / 60000);
  if (m < 1) return "just now";
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  const days = Math.floor(h / 24);
  if (days < 7) return `${days}d ago`;
  return new Date(ts).toLocaleDateString();
}

export default function Sidebar({
  sessions,
  activeId,
  open,
  health,
  onSelect,
  onNew,
  onDelete,
  onClose,
  onRetryHealth,
}: Props) {
  return (
    <>
      <div
        onClick={onClose}
        className={`fixed inset-0 z-30 bg-black/40 backdrop-blur-sm transition-opacity md:hidden ${
          open ? "opacity-100" : "pointer-events-none opacity-0"
        }`}
      />
      <aside
        className={`fixed z-40 flex h-full w-[264px] flex-col border-r transition-transform duration-200 md:static md:z-auto md:translate-x-0 ${
          open ? "translate-x-0" : "-translate-x-full"
        }`}
        style={{ background: "var(--sidebar)", borderColor: "var(--border)" }}
      >
        <div className="flex items-center gap-2.5 px-3 pb-2 pt-4">
          <BrandMark size={28} />
          <div className="min-w-0 flex-1 leading-tight">
            <div className="truncate text-[13.5px] font-semibold tracking-tight">
              DevSec Brief
            </div>
            <button
              onClick={onRetryHealth}
              title="Check backend health"
              className="mt-0.5 flex items-center gap-1.5 text-[11.5px] hover:opacity-80"
              style={{ color: "var(--muted)" }}
            >
              <span
                className="inline-block h-[6px] w-[6px] rounded-full"
                style={{
                  background:
                    health === "ok"
                      ? "var(--success)"
                      : health === "checking"
                        ? "var(--warning)"
                        : "var(--danger)",
                }}
              />
              {health === "ok"
                ? "API connected"
                : health === "checking"
                  ? "Connecting…"
                  : "API unreachable"}
            </button>
          </div>
          <button
            onClick={onClose}
            className="rounded-md px-2 py-1 text-lg leading-none md:hidden"
            style={{ color: "var(--muted)" }}
            aria-label="Close sidebar"
          >
            ×
          </button>
        </div>

        <div className="px-3 pt-2">
          <button
            onClick={onNew}
            className="lift flex w-full items-center gap-2.5 rounded-xl border px-3 py-2.5 text-left text-[13.5px] font-medium"
            style={{
              background: "var(--surface)",
              borderColor: "var(--border)",
              color: "var(--text)",
            }}
          >
            <span
              className="grid h-5 w-5 shrink-0 place-items-center rounded-full text-[15px] leading-none"
              style={{ background: "var(--accent)", color: "var(--bg)" }}
            >
              +
            </span>
            New chat
          </button>
        </div>

        <div
          className="px-4 pb-1.5 pt-5 text-[11px] font-semibold uppercase tracking-[0.12em]"
          style={{ color: "var(--faint)" }}
        >
          Chats
        </div>

        <div className="nice-scroll flex-1 space-y-0.5 overflow-y-auto px-2 pb-3">
          {sessions.length === 0 && (
            <p
              className="px-2 py-4 text-[13px]"
              style={{ color: "var(--muted)" }}
            >
              No conversations yet.
            </p>
          )}
          {sessions.map((s) => {
            const active = s.id === activeId;
            return (
              <div
                key={s.id}
                className="group flex items-center rounded-xl"
                style={
                  active
                    ? {
                        background: "var(--surface-3)",
                      }
                    : undefined
                }
              >
                <button
                  onClick={() => onSelect(s.id)}
                  className="min-w-0 flex-1 rounded-xl px-3 py-2 text-left"
                >
                  <div className="truncate text-[13px] font-medium leading-snug">
                    {s.title || "Untitled"}
                  </div>
                  <div
                    className="mt-0.5 text-[11px]"
                    style={{ color: "var(--faint)" }}
                  >
                    {s.messages.length === 0
                      ? "Empty"
                      : `${Math.ceil(s.messages.length / 2)} messages · ${timeAgo(s.updatedAt)}`}
                  </div>
                </button>
                <button
                  onClick={() => onDelete(s.id)}
                  title="Delete chat"
                  aria-label="Delete chat"
                  className="mr-1.5 shrink-0 rounded-md px-2 py-1 text-[15px] leading-none transition-opacity md:opacity-0 md:group-hover:opacity-100"
                  style={{ color: "var(--faint)" }}
                >
                  ×
                </button>
              </div>
            );
          })}
        </div>

        <div
          className="border-t px-4 py-3 text-[11px] leading-relaxed"
          style={{ borderColor: "var(--border)", color: "var(--faint)" }}
        >
          Grounded answers with cited sources.
        </div>
      </aside>
    </>
  );
}
