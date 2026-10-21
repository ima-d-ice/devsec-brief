"use client";

import { useEffect, useRef, useState } from "react";
import type { ChatSettings, Topic } from "@/lib/types";

interface Props {
  busy: boolean;
  settings: ChatSettings;
  onSettings: (patch: Partial<ChatSettings>) => void;
  onSend: (text: string) => void;
  onStop: () => void;
}

const TOPICS: { value: Topic; label: string }[] = [
  { value: "all", label: "All topics" },
  { value: "webdev", label: "Web dev" },
  { value: "cybersec", label: "Security" },
];

export default function Composer({
  busy,
  settings,
  onSettings,
  onSend,
  onStop,
}: Props) {
  const [value, setValue] = useState("");
  const ref = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = Math.min(el.scrollHeight, 180) + "px";
  }, [value]);

  useEffect(() => {
    ref.current?.focus();
  }, []);

  const submit = () => {
    const q = value.trim();
    if (!q || busy) return;
    if (q.length > 2000) return;
    onSend(q);
    setValue("");
    requestAnimationFrame(() => {
      if (ref.current) {
        ref.current.style.height = "auto";
        ref.current.focus();
      }
    });
  };

  const tooLong = value.length > 2000;

  return (
    <div className="sticky bottom-0 z-10 px-3 pb-3 pt-2 sm:px-5 sm:pb-5">
      <div className="mx-auto w-full max-w-3xl">
        <div
          className="composer-focus rounded-[26px] border transition-all"
          style={{
            background: "var(--surface)",
            borderColor: tooLong ? "var(--danger)" : "var(--border-strong)",
            boxShadow: "var(--composer-shadow)",
          }}
        >
          <textarea
            ref={ref}
            value={value}
            onChange={(e) => setValue(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                submit();
              }
            }}
            rows={1}
            placeholder="Message DevSec Brief…"
            data-testid="composer-textarea"
            className="nice-scroll max-h-[180px] w-full resize-none bg-transparent px-4 pb-1 pt-3.5 text-[14.5px] leading-relaxed outline-none placeholder:text-[var(--faint)]"
            style={{ color: "var(--text)" }}
          />

          <div className="flex items-center gap-2 px-2.5 pb-2.5 pt-1">
            <div className="hidden items-center gap-1.5 sm:flex">
              <select
                value={settings.topic}
                onChange={(e) =>
                  onSettings({ topic: e.target.value as Topic })
                }
                title="News topic"
                className="cursor-pointer appearance-none rounded-full border bg-transparent px-2.5 py-1 text-[11.5px] font-medium outline-none hover:bg-black/5 dark:hover:bg-white/10"
                style={{
                  borderColor: "var(--border)",
                  color: "var(--muted)",
                }}
              >
                {TOPICS.map((t) => (
                  <option key={t.value} value={t.value}>
                    {t.label}
                  </option>
                ))}
              </select>

              <select
                value={settings.k}
                onChange={(e) => onSettings({ k: Number(e.target.value) })}
                title="Retrieval depth (k)"
                className="cursor-pointer appearance-none rounded-full border bg-transparent px-2.5 py-1 text-[11.5px] font-medium outline-none hover:bg-black/5 dark:hover:bg-white/10"
                style={{
                  borderColor: "var(--border)",
                  color: "var(--muted)",
                }}
              >
                {[3, 5, 6, 10].map((k) => (
                  <option key={k} value={k}>
                    k={k}
                  </option>
                ))}
              </select>

              <button
                onClick={() =>
                  onSettings({ streamEnabled: !settings.streamEnabled })
                }
                title={
                  settings.streamEnabled
                    ? "Streaming on — switch to single-response mode"
                    : "Single-response mode — switch to streaming"
                }
                className="flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[11.5px] font-medium"
                style={
                  settings.streamEnabled
                    ? {
                        borderColor: "var(--border)",
                        color: "var(--text)",
                      }
                    : {
                        borderColor: "var(--border)",
                        color: "var(--faint)",
                      }
                }
              >
                <span
                  className="inline-block h-[6px] w-[6px] rounded-full"
                  style={{
                    background: settings.streamEnabled
                      ? "var(--success)"
                      : "var(--faint)",
                  }}
                />
                Stream
              </button>
            </div>

            {value.length > 1500 && (
              <span
                className="font-mono text-[11px]"
                style={{ color: tooLong ? "var(--danger)" : "var(--faint)" }}
              >
                {value.length}/2000
              </span>
            )}

            <div className="ml-auto">
              {busy ? (
                <button
                  onClick={onStop}
                  className="grid h-8 w-8 place-items-center rounded-full transition-opacity hover:opacity-80"
                  style={{ background: "var(--accent)", color: "var(--bg)" }}
                  title="Stop generating"
                >
                  <span
                    className="inline-block h-2.5 w-2.5 rounded-[2px]"
                    style={{ background: "var(--bg)" }}
                  />
                </button>
              ) : (
                <button
                  onClick={submit}
                  disabled={!value.trim() || tooLong}
                  data-testid="send-button"
                  className="grid h-8 w-8 place-items-center rounded-full text-[15px] font-semibold transition-opacity disabled:cursor-not-allowed disabled:opacity-30"
                  style={{ background: "var(--accent)", color: "var(--bg)" }}
                  title="Send message"
                >
                  ↑
                </button>
              )}
            </div>
          </div>
        </div>
        <p
          className="mt-2 text-center text-[11px]"
          style={{ color: "var(--faint)" }}
        >
          DevSec Brief can make mistakes — verify claims via the cited sources.
        </p>
      </div>
    </div>
  );
}
