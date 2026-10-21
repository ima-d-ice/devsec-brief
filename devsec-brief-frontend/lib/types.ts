export type Topic = "all" | "webdev" | "cybersec";

export interface Source {
  title?: string | null;
  url?: string | null;
  source?: string | null;
  category?: string | null;
  published_at?: string | null;
}

export interface RetrievalTimings {
  total_retrieval_ms?: number;
  [key: string]: number | undefined;
}

export interface ChatMetrics {
  cache_hit?: boolean;
  model_used?: string | null;
  ttft_ms?: number;
  tps?: number;
  tokens?: number;
  stream_duration_ms?: number;
  cache_lookup_ms?: number;
  retrieval_timings?: RetrievalTimings | null;
  latency_breakdown_ms?: Record<string, number> | null;
}

export type ChatRole = "user" | "assistant";

export interface ChatMessage {
  id: string;
  role: ChatRole;
  content: string;
  sources?: Source[];
  metrics?: ChatMetrics | null;
  pending?: boolean;
  error?: string | null;
}

export interface ChatSession {
  id: string;
  backendSessionId: string;
  title: string;
  createdAt: number;
  updatedAt: number;
  messages: ChatMessage[];
}

export interface ChatSettings {
  topic: Topic;
  k: number;
  streamEnabled: boolean;
  theme: "light" | "dark" | "system";
}
