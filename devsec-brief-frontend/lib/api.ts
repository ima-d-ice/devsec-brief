import type { ChatMetrics, Source, Topic } from "./types";

export const API_URL =
  process.env.NEXT_PUBLIC_API_URL?.replace(/\/$/, "") ||
  "http://127.0.0.1:8000";

export interface AskPayload {
  query: string;
  topic: Topic;
  k: number;
  session_id: string;
}

function toBackendTopic(topic: Topic): string | null {
  return topic === "all" ? null : topic;
}

export async function checkHealth(signal?: AbortSignal): Promise<boolean> {
  try {
    const res = await fetch(`${API_URL}/health`, { signal });
    if (!res.ok) return false;
    const data = await res.json();
    return data?.status === "ok";
  } catch {
    return false;
  }
}

export interface AskJsonResult {
  answer: string;
  sources: Source[];
  model_used?: string | null;
  cache_hit: boolean;
  latency_breakdown_ms?: Record<string, number> | null;
}

export async function askJson(
  payload: AskPayload,
  signal?: AbortSignal
): Promise<AskJsonResult> {
  const res = await fetch(`${API_URL}/ask`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      query: payload.query,
      topic: toBackendTopic(payload.topic),
      k: payload.k,
      session_id: payload.session_id,
    }),
    signal,
  });
  if (!res.ok) {
    let detail = `Request failed (${res.status})`;
    try {
      const err = await res.json();
      if (typeof err?.detail === "string") detail = err.detail;
      else if (Array.isArray(err?.detail) && err.detail[0]?.msg)
        detail = err.detail[0].msg;
    } catch {
      /* keep default */
    }
    throw new Error(detail);
  }
  return res.json();
}

export interface StreamCallbacks {
  onSources?: (sources: Source[], sessionId: string, cacheHit: boolean) => void;
  onToken?: (token: string) => void;
  onMetrics?: (metrics: ChatMetrics) => void;
  onError?: (message: string) => void;
  onDone?: () => void;
}

interface SSEEvent {
  event: string;
  data: string;
}

function parseSSEBlock(block: string): SSEEvent | null {
  let event = "";
  const dataLines: string[] = [];
  for (const line of block.split("\n")) {
    if (line.startsWith("event:")) event = line.slice(6).trim();
    else if (line.startsWith("data:")) dataLines.push(line.slice(5).trimStart());
  }
  if (!event && dataLines.length === 0) return null;
  return { event: event || "message", data: dataLines.join("\n") };
}

export async function askStream(
  payload: AskPayload,
  cb: StreamCallbacks,
  signal?: AbortSignal
): Promise<void> {
  const res = await fetch(`${API_URL}/ask/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
    body: JSON.stringify({
      query: payload.query,
      topic: toBackendTopic(payload.topic),
      k: payload.k,
      session_id: payload.session_id,
    }),
    signal,
  });

  if (!res.ok || !res.body) {
    let detail = `Stream failed (${res.status})`;
    try {
      const err = await res.json();
      if (typeof err?.detail === "string") detail = err.detail;
    } catch {
      /* ignore */
    }
    throw new Error(detail);
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let doneFired = false;
  const fireDone = () => {
    if (!doneFired) {
      doneFired = true;
      cb.onDone?.();
    }
  };

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      // SSE frames are separated by blank lines
      let idx: number;
      while ((idx = buffer.indexOf("\n\n")) !== -1) {
        const raw = buffer.slice(0, idx);
        buffer = buffer.slice(idx + 2);
        const evt = parseSSEBlock(raw);
        if (!evt) continue;
        let data: Record<string, unknown> = {};
        try {
          data = evt.data ? JSON.parse(evt.data) : {};
        } catch {
          continue;
        }
        if (evt.event === "sources") {
          cb.onSources?.(
            (data.sources as Source[]) ?? [],
            (data.session_id as string) ?? payload.session_id,
            Boolean(data.cache_hit)
          );
        } else if (evt.event === "token") {
          if (typeof data.content === "string" && data.content.length > 0)
            cb.onToken?.(data.content);
        } else if (evt.event === "metrics") {
          cb.onMetrics?.(data as unknown as ChatMetrics);
        } else if (evt.event === "error") {
          cb.onError?.(
            typeof data.message === "string"
              ? data.message
              : "No relevant news found."
          );
        } else if (evt.event === "done") {
          fireDone();
        }
      }
    }
    // flush trailing buffer
    const tail = buffer.trim();
    if (tail) {
      const evt = parseSSEBlock(tail);
      if (evt?.event === "error") {
        try {
          const data = JSON.parse(evt.data);
          cb.onError?.(
            typeof data.message === "string" ? data.message : "Stream error."
          );
        } catch {
          cb.onError?.("Stream error.");
        }
      }
    }
    fireDone();
  } finally {
    reader.releaseLock();
  }
}

export function uid(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto)
    return crypto.randomUUID();
  return `id-${Date.now()}-${Math.random().toString(36).slice(2, 9)}`;
}
