"use client";

import type { ChatMessage } from "@/lib/types";
import Markdown from "./Markdown";
import Sources from "./Sources";
import Metrics from "./Metrics";
import { ShieldIcon } from "./Brand";

interface Props {
  message: ChatMessage;
  onCopy: (text: string) => void;
  onRegenerate?: () => void;
  copied: boolean;
  isLastAssistant: boolean;
  busy: boolean;
}

export default function Message({
  message,
  onCopy,
  onRegenerate,
  copied,
  isLastAssistant,
  busy,
}: Props) {
  if (message.role === "user") {
    return (
      <div
        className="flex justify-end"
        data-testid="user-message"
      >
        <div
          className="max-w-[85%] whitespace-pre-wrap rounded-3xl rounded-br-lg px-4 py-2.5 text-[14.5px] leading-relaxed sm:max-w-[75%]"
          style={{ background: "var(--user-bg)", color: "var(--user-text)" }}
        >
          {message.content}
        </div>
      </div>
    );
  }

  const isPendingEmpty = message.pending && !message.content;

  return (
    <div className="flex gap-3" data-testid="assistant-message">
      <div
        className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full"
        style={{ background: "var(--brand)", color: "var(--brand-text)" }}
      >
        <ShieldIcon size={14} />
      </div>
      <div className="min-w-0 flex-1 pt-0.5">
        {isPendingEmpty ? (
          <div className="flex items-center gap-1.5 py-2">
            <span className="typing-dot" />
            <span className="typing-dot" />
            <span className="typing-dot" />
          </div>
        ) : (
          <div className={message.pending ? "caret" : ""} data-testid="answer-body">
            <Markdown text={message.content || ""} />
          </div>
        )}

        {message.error && !isPendingEmpty && (
          <div
            className="mt-2 rounded-xl border px-3 py-2 text-xs"
            style={{
              borderColor: "var(--border)",
              background: "var(--surface-2)",
              color: "var(--muted)",
            }}
          >
            {message.error}
          </div>
        )}

        {!isPendingEmpty && message.sources && message.sources.length > 0 && (
          <Sources sources={message.sources} />
        )}
        {!isPendingEmpty && <Metrics metrics={message.metrics} />}

        {!message.pending && message.content && (
          <div className="mt-1.5 flex items-center gap-0.5">
            <button
              onClick={() => onCopy(message.content)}
              className="rounded-lg px-2 py-1 text-[11.5px] hover:bg-black/5 dark:hover:bg-white/10"
              style={{ color: "var(--faint)" }}
              title="Copy answer"
            >
              {copied ? "Copied" : "Copy"}
            </button>
            {isLastAssistant && onRegenerate && !busy && (
              <button
                onClick={onRegenerate}
                className="rounded-lg px-2 py-1 text-[11.5px] hover:bg-black/5 dark:hover:bg-white/10"
                style={{ color: "var(--faint)" }}
                title="Regenerate answer"
              >
                Retry
              </button>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
