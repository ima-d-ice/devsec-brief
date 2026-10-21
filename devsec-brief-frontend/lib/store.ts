import type { ChatSession, ChatSettings } from "./types";
import { uid } from "./api";

const SESSIONS_KEY = "devsec.sessions.v1";
const ACTIVE_KEY = "devsec.activeId.v1";
const SETTINGS_KEY = "devsec.settings.v1";

export const DEFAULT_SETTINGS: ChatSettings = {
  topic: "all",
  k: 6,
  streamEnabled: true,
  theme: "system",
};

export function newSessionId(): string {
  return uid();
}

export function createSession(firstQuery?: string): ChatSession {
  const now = Date.now();
  const title = firstQuery
    ? firstQuery.trim().slice(0, 42) + (firstQuery.trim().length > 42 ? "…" : "")
    : "New investigation";
  return {
    id: uid(),
    backendSessionId: uid(),
    title,
    createdAt: now,
    updatedAt: now,
    messages: [],
  };
}

export function loadSessions(): ChatSession[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = localStorage.getItem(SESSIONS_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed.filter((s) => s && typeof s.id === "string");
  } catch {
    return [];
  }
}

export function saveSessions(sessions: ChatSession[]): void {
  try {
    localStorage.setItem(SESSIONS_KEY, JSON.stringify(sessions.slice(0, 50)));
  } catch {
    /* storage full — ignore */
  }
}

export function loadActiveId(): string | null {
  if (typeof window === "undefined") return null;
  try {
    return localStorage.getItem(ACTIVE_KEY);
  } catch {
    return null;
  }
}

export function saveActiveId(id: string): void {
  try {
    localStorage.setItem(ACTIVE_KEY, id);
  } catch {
    /* ignore */
  }
}

export function loadSettings(): ChatSettings {
  if (typeof window === "undefined") return DEFAULT_SETTINGS;
  try {
    const raw = localStorage.getItem(SETTINGS_KEY);
    if (!raw) return DEFAULT_SETTINGS;
    const parsed = JSON.parse(raw);
    return {
      topic:
        parsed.topic === "webdev" || parsed.topic === "cybersec"
          ? parsed.topic
          : "all",
      k:
        typeof parsed.k === "number"
          ? Math.max(1, Math.min(20, parsed.k))
          : DEFAULT_SETTINGS.k,
      streamEnabled:
        typeof parsed.streamEnabled === "boolean"
          ? parsed.streamEnabled
          : true,
      theme:
        parsed.theme === "light" || parsed.theme === "dark"
          ? parsed.theme
          : "system",
    };
  } catch {
    return DEFAULT_SETTINGS;
  }
}

export function saveSettings(s: ChatSettings): void {
  try {
    localStorage.setItem(SETTINGS_KEY, JSON.stringify(s));
  } catch {
    /* ignore */
  }
}
