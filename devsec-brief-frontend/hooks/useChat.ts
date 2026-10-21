"use client";

/* eslint-disable react-hooks/set-state-in-effect -- localStorage hydration and health polling intentionally sync external state on mount */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { askJson, askStream, checkHealth, uid } from "@/lib/api";
import {
  createSession,
  loadActiveId,
  loadSessions,
  loadSettings,
  saveActiveId,
  saveSessions,
  saveSettings,
} from "@/lib/store";
import type {
  ChatMessage,
  ChatSession,
  ChatSettings,
  Source,
} from "@/lib/types";

type Status = "idle" | "loading" | "streaming";
type Health = "checking" | "ok" | "down";

function titleFromQuery(q: string): string {
  const t = q.trim().replace(/\s+/g, " ");
  return t.slice(0, 42) + (t.length > 42 ? "…" : "");
}

const REFUSAL_RE = /not enough info|no relevant news/i;

function friendlyRefusal(): string {
  return (
    "I couldn't find enough in the news index to answer that reliably — " +
    "the retrieved articles didn't cover it.\n\nTry rephrasing with specifics " +
    "(product name, CVE ID, or timeframe), or start a new chat for a different topic."
  );
}

export function useChat() {
  const [sessions, setSessions] = useState<ChatSession[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [settings, setSettingsState] = useState<ChatSettings>({
    topic: "all",
    k: 6,
    streamEnabled: true,
    theme: "system",
  });
  const [status, setStatus] = useState<Status>("idle");
  const [health, setHealth] = useState<Health>("checking");
  const [hydrated, setHydrated] = useState(false);
  const abortRef = useRef<AbortController | null>(null);

  // ---- hydration (localStorage only on client) ----
  useEffect(() => {
    const stored = loadSessions();
    const active = loadActiveId();
    const s = loadSettings();
    setSettingsState(s);
    if (stored.length === 0) {
      const fresh = createSession();
      setSessions([fresh]);
      setActiveId(fresh.id);
    } else {
      setSessions(stored);
      setActiveId(active && stored.some((x) => x.id === active) ? active : stored[0].id);
    }
    setHydrated(true);
  }, []);

  useEffect(() => {
    if (!hydrated) return;
    saveSessions(sessions);
  }, [sessions, hydrated]);

  useEffect(() => {
    if (!hydrated || !activeId) return;
    saveActiveId(activeId);
  }, [activeId, hydrated]);

  useEffect(() => {
    if (!hydrated) return;
    saveSettings(settings);
  }, [settings, hydrated]);

  // ---- theme ----
  useEffect(() => {
    const root = document.documentElement;
    const apply = () => {
      const prefersDark = window.matchMedia(
        "(prefers-color-scheme: dark)"
      ).matches;
      const dark =
        settings.theme === "dark" ||
        (settings.theme === "system" && prefersDark);
      root.dataset.theme = dark ? "dark" : "light";
      root.classList.toggle("dark", dark);
    };
    apply();
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const listener = () => {
      if (settings.theme === "system") apply();
    };
    mq.addEventListener("change", listener);
    return () => mq.removeEventListener("change", listener);
  }, [settings.theme]);

  // ---- health poll ----
  const refreshHealth = useCallback(async () => {
    setHealth("checking");
    const ok = await checkHealth();
    setHealth(ok ? "ok" : "down");
  }, []);

  useEffect(() => {
    refreshHealth();
    const t = setInterval(refreshHealth, 30000);
    return () => clearInterval(t);
  }, [refreshHealth]);

  const activeSession = useMemo(
    () => sessions.find((s) => s.id === activeId) ?? null,
    [sessions, activeId]
  );

  const patchMessage = useCallback(
    (sessionId: string, messageId: string, patch: Partial<ChatMessage>) => {
      setSessions((prev) =>
        prev.map((s) =>
          s.id !== sessionId
            ? s
            : {
                ...s,
                updatedAt: Date.now(),
                messages: s.messages.map((m) =>
                  m.id === messageId ? { ...m, ...patch } : m
                ),
              }
        )
      );
    },
    []
  );

  const setSettings = useCallback((patch: Partial<ChatSettings>) => {
    setSettingsState((prev) => ({ ...prev, ...patch }));
  }, []);

  const stop = useCallback(() => {
    abortRef.current?.abort();
    abortRef.current = null;
    setStatus("idle");
  }, []);

  const newChat = useCallback(() => {
    stop();
    const fresh = createSession();
    setSessions((prev) => [fresh, ...prev]);
    setActiveId(fresh.id);
  }, [stop]);

  const selectChat = useCallback(
    (id: string) => {
      if (status !== "idle") stop();
      setActiveId(id);
    },
    [status, stop]
  );

  const deleteChat = useCallback(
    (id: string) => {
      setSessions((prev) => {
        const next = prev.filter((s) => s.id !== id);
        if (next.length === 0) {
          const fresh = createSession();
          setActiveId(fresh.id);
          return [fresh];
        }
        if (id === activeId) setActiveId(next[0].id);
        return next;
      });
    },
    [activeId]
  );

  const send = useCallback(
    async (rawQuery: string) => {
      const query = rawQuery.trim();
      if (!query || status !== "idle") return;
      if (query.length > 2000) return;

      let sessionId = activeId;
      let backendSessionId = activeSession?.backendSessionId ?? uid();

      // create a session on the fly if none exists
      if (!sessionId || !activeSession) {
        const fresh = createSession(query);
        backendSessionId = fresh.backendSessionId;
        setSessions((prev) => [fresh, ...prev]);
        setActiveId(fresh.id);
        sessionId = fresh.id;
      }

      const targetSessionId = sessionId as string;
      const userMsg: ChatMessage = { id: uid(), role: "user", content: query };
      const assistantId = uid();
      const assistantMsg: ChatMessage = {
        id: assistantId,
        role: "assistant",
        content: "",
        sources: [],
        pending: true,
        error: null,
      };

      setSessions((prev) =>
        prev.map((s) =>
          s.id !== targetSessionId
            ? s
            : {
                ...s,
                title:
                  s.messages.length === 0 ? titleFromQuery(query) : s.title,
                updatedAt: Date.now(),
                messages: [...s.messages, userMsg, assistantMsg],
              }
        )
      );

      const controller = new AbortController();
      abortRef.current = controller;
      const useStream = settings.streamEnabled;
      setStatus(useStream ? "streaming" : "loading");

      // Contextualize short follow-ups for retrieval: the backend retrieves
      // on the raw query only (history is fed to the LLM, not the retriever),
      // so a follow-up like "explain that more simply" would retrieve
      // unrelated docs and yield "Not enough info". Prepend the previous
      // question so hybrid search finds the right context. The chat bubble
      // still shows the user's original text.
      let backendQuery = query;
      const prevUser = activeSession
        ? [...activeSession.messages]
            .reverse()
            .find((m) => m.role === "user" && m.content.trim() !== query)
        : undefined;
      if (prevUser && query.length < 120) {
        backendQuery = `${prevUser.content}\nFollow-up: ${query}`;
        if (backendQuery.length > 2000)
          backendQuery = backendQuery.slice(0, 2000);
      }

      const payload = {
        query: backendQuery,
        topic: settings.topic,
        k: settings.k,
        session_id: backendSessionId,
      };

      const appendToken = (token: string) => {
        setSessions((prev) =>
          prev.map((s) =>
            s.id !== targetSessionId
              ? s
              : {
                  ...s,
                  updatedAt: Date.now(),
                  messages: s.messages.map((m) =>
                    m.id === assistantId
                      ? { ...m, content: m.content + token }
                      : m
                  ),
                }
          )
        );
      };

      try {
        if (useStream) {
          let gotToken = false;
          let streamFailed = false;
          let fullText = "";
          try {
            await askStream(
              payload,
              {
                onSources: (
                  sources: Source[],
                  sid: string,
                  cacheHit: boolean
                ) => {
                  // keep backend session id in sync (server may echo a new one)
                  setSessions((prev) =>
                    prev.map((s) =>
                      s.id !== targetSessionId
                        ? s
                        : { ...s, backendSessionId: sid }
                    )
                  );
                  patchMessage(targetSessionId, assistantId, {
                    sources,
                    metrics: { cache_hit: cacheHit },
                  });
                },
                onToken: (t) => {
                  gotToken = true;
                  fullText += t;
                  appendToken(t);
                },
                onMetrics: (metrics) => {
                  patchMessage(targetSessionId, assistantId, {
                    metrics: {
                      cache_hit: metrics.cache_hit,
                      model_used: metrics.model_used,
                      ttft_ms: metrics.ttft_ms,
                      tps: metrics.tps,
                      tokens: metrics.tokens,
                      stream_duration_ms: metrics.stream_duration_ms,
                      cache_lookup_ms: metrics.cache_lookup_ms,
                      retrieval_timings: metrics.retrieval_timings ?? null,
                    },
                  });
                },
                onError: (message) => {
                  patchMessage(targetSessionId, assistantId, {
                    content:
                      "Not enough info in the index for that yet — try rephrasing or a broader query.",
                    error: message,
                    pending: false,
                  });
                },
                onDone: () => {
                  patchMessage(targetSessionId, assistantId, { pending: false });
                },
              },
              controller.signal
            );
          } catch (e) {
            if ((e as Error).name === "AbortError") {
              patchMessage(targetSessionId, assistantId, { pending: false });
              return;
            }
            streamFailed = true;
          }

          // Fallback to JSON endpoint if stream produced nothing
          if (streamFailed && !gotToken) {
            const json = await askJson(payload, controller.signal);
            patchMessage(targetSessionId, assistantId, {
              content: REFUSAL_RE.test(json.answer)
                ? friendlyRefusal()
                : json.answer,
              sources: json.sources,
              metrics: {
                cache_hit: json.cache_hit,
                model_used: json.model_used,
                latency_breakdown_ms: json.latency_breakdown_ms,
              },
              pending: false,
              error: null,
            });
          } else if (gotToken && REFUSAL_RE.test(fullText.trim())) {
            // Backend LLM refused on irrelevant retrieval — explain instead
            // of showing the bare refusal.
            patchMessage(targetSessionId, assistantId, {
              content: friendlyRefusal(),
              pending: false,
            });
          } else {
            patchMessage(targetSessionId, assistantId, { pending: false });
          }
        } else {
          const json = await askJson(payload, controller.signal);
          patchMessage(targetSessionId, assistantId, {
            content: REFUSAL_RE.test(json.answer)
              ? friendlyRefusal()
              : json.answer,
            sources: json.sources,
            metrics: {
              cache_hit: json.cache_hit,
              model_used: json.model_used,
              latency_breakdown_ms: json.latency_breakdown_ms,
            },
            pending: false,
            error: null,
          });
        }
      } catch (e) {
        if ((e as Error).name === "AbortError") {
          patchMessage(targetSessionId, assistantId, { pending: false });
        } else {
          patchMessage(targetSessionId, assistantId, {
            content:
              "The backend is unreachable. Start the API on :8000 and try again.",
            error: e instanceof Error ? e.message : "Request failed",
            pending: false,
          });
          setHealth("down");
        }
      } finally {
        abortRef.current = null;
        setStatus("idle");
      }
    },
    [activeId, activeSession, patchMessage, settings, status]
  );

  const regenerate = useCallback(() => {
    const sess = activeSession;
    if (!sess || status !== "idle" || sess.messages.length === 0) return;
    const lastUser = [...sess.messages].reverse().find((m) => m.role === "user");
    if (!lastUser) return;
    // drop the last assistant message, then resend
    const targetId = sess.id;
    setSessions((prev) =>
      prev.map((s) =>
        s.id !== targetId
          ? s
          : {
              ...s,
              messages: s.messages.filter(
                (_, i, arr) =>
                  !(
                    i === arr.length - 1 &&
                    arr[arr.length - 1].role === "assistant"
                  )
              ),
            }
      )
    );
    // defer so state settles
    setTimeout(() => send(lastUser.content), 50);
  }, [activeSession, send, status]);

  const isBusy = status !== "idle";

  return {
    sessions,
    activeId,
    activeSession,
    settings,
    setSettings,
    status,
    isBusy,
    health,
    refreshHealth,
    hydrated,
    send,
    regenerate,
    stop,
    newChat,
    selectChat,
    deleteChat,
  };
}
