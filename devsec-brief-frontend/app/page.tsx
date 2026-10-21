"use client";

import { useEffect, useRef, useState } from "react";
import { useChat } from "@/hooks/useChat";
import Sidebar from "@/components/Sidebar";
import Topbar from "@/components/Topbar";
import EmptyState from "@/components/EmptyState";
import Message from "@/components/Message";
import Composer from "@/components/Composer";

export default function Home() {
  const chat = useChat();
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [copiedId, setCopiedId] = useState<string | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const bottomRef = useRef<HTMLDivElement>(null);

  const { activeSession, isBusy } = chat;

  // auto-scroll on new tokens
  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    const nearBottom =
      el.scrollHeight - el.scrollTop - el.clientHeight < 220;
    if (nearBottom || isBusy) {
      bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
    }
  }, [activeSession?.messages, isBusy]);

  // close sidebar on desktop
  useEffect(() => {
    const mq = window.matchMedia("(min-width: 768px)");
    const sync = () => {
      if (mq.matches) setSidebarOpen(false);
    };
    sync();
    mq.addEventListener("change", sync);
    return () => mq.removeEventListener("change", sync);
  }, []);

  const handleCopy = async (id: string, text: string) => {
    try {
      await navigator.clipboard.writeText(text);
      setCopiedId(id);
      setTimeout(() => setCopiedId((c) => (c === id ? null : c)), 1600);
    } catch {
      /* clipboard unavailable */
    }
  };

  const messages = activeSession?.messages ?? [];
  const lastAssistantIdx = (() => {
    for (let i = messages.length - 1; i >= 0; i--) {
      if (messages[i].role === "assistant") return i;
    }
    return -1;
  })();
  const modelLabel =
    lastAssistantIdx >= 0
      ? (messages[lastAssistantIdx].metrics?.model_used ?? null)
      : null;

  return (
    <div className="relative flex h-dvh overflow-hidden">
      <Sidebar
        sessions={chat.sessions}
        activeId={chat.activeId}
        open={sidebarOpen}
        health={chat.health}
        onSelect={(id) => {
          chat.selectChat(id);
          setSidebarOpen(false);
        }}
        onNew={chat.newChat}
        onDelete={chat.deleteChat}
        onClose={() => setSidebarOpen(false)}
        onRetryHealth={chat.refreshHealth}
      />

      <div className="relative z-10 flex min-w-0 flex-1 flex-col">
        <Topbar
          settings={chat.settings}
          busy={isBusy}
          modelLabel={modelLabel}
          onToggleSidebar={() => setSidebarOpen((v) => !v)}
          onSettings={chat.setSettings}
          onNew={chat.newChat}
        />

        {chat.health === "down" && (
          <div
            className="flex items-center gap-3 border-b px-4 py-2.5 text-[13px] sm:px-5"
            style={{
              borderColor: "var(--border)",
              background: "var(--surface)",
              color: "var(--muted)",
            }}
          >
            <span style={{ color: "var(--danger)" }}>●</span>
            Backend unreachable at :8000 — start it with{" "}
            <code
              className="rounded px-1.5 py-0.5 font-mono text-xs"
              style={{ background: "var(--surface-2)" }}
            >
              docker compose up
            </code>
            <button
              onClick={chat.refreshHealth}
              className="ml-auto rounded-full border px-3 py-1 text-xs font-medium"
              style={{ borderColor: "var(--border)" }}
            >
              Retry
            </button>
          </div>
        )}

        <div
          ref={scrollRef}
          className="nice-scroll flex-1 overflow-y-auto px-3 sm:px-5"
        >
          {messages.length === 0 ? (
            <EmptyState onPick={(q) => chat.send(q)} />
          ) : (
            <div className="mx-auto w-full max-w-3xl space-y-7 py-8">
              {messages.map((m, i) => (
                <Message
                  key={m.id}
                  message={m}
                  copied={copiedId === m.id}
                  onCopy={(t) => handleCopy(m.id, t)}
                  onRegenerate={
                    i === lastAssistantIdx ? chat.regenerate : undefined
                  }
                  isLastAssistant={i === lastAssistantIdx}
                  busy={isBusy}
                />
              ))}
              <div ref={bottomRef} className="h-2" />
            </div>
          )}
        </div>

        <Composer
          busy={isBusy}
          settings={chat.settings}
          onSettings={chat.setSettings}
          onSend={(t) => chat.send(t)}
          onStop={chat.stop}
        />
      </div>
    </div>
  );
}
