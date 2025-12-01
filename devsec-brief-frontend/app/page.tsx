"use client";

import { useState } from "react";

type Topic = "all" | "webdev" | "cybersec";

interface Source {
  title?: string | null;
  url?: string | null;
  source?: string | null;
  category?: string | null;
  published_at?: string | null;
}

interface AskResponse {
  answer: string;
  sources: Source[];
}

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000";

export default function HomePage() {
  const [query, setQuery] = useState("");
  const [topic, setTopic] = useState<Topic>("all");
  const [k, setK] = useState(6);

  const [loading, setLoading] = useState(false);
  const [answer, setAnswer] = useState<string>("");
  const [sources, setSources] = useState<Source[]>([]);
  const [error, setError] = useState<string | null>(null);

  const handleAsk = async () => {
    const trimmed = query.trim();
    if (!trimmed) {
      setError("Please enter a question.");
      return;
    }

    setLoading(true);
    setError(null);
    setAnswer("");
    setSources([]);

    try {
      const body = {
        query: trimmed,
        topic: topic === "all" ? null : topic,
        k,
      };

      const res = await fetch(`${API_BASE}/ask`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify(body),
      });

      if (!res.ok) {
        const msg = `API error: ${res.status}`;
        console.error(msg);
        setError(msg);
        return;
      }

      const data: AskResponse = await res.json();
      setAnswer(data.answer ?? "");
      setSources(Array.isArray(data.sources) ? data.sources : []);
    } catch (err) {
      console.error(err);
      setError("Failed to reach backend. Is FastAPI running?");
    } finally {
      setLoading(false);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
      e.preventDefault();
      if (!loading) handleAsk();
    }
  };

  return (
    <main className="min-h-screen bg-slate-950 text-slate-100">
      <div className="mx-auto max-w-4xl px-4 pb-16 pt-10">
        {/* Header */}
        <header className="mb-6">
          <h1 className="text-2xl font-semibold tracking-tight text-slate-50">
            DevSec Brief
          </h1>
          <p className="mt-1 text-sm text-slate-400">
            RAG-powered assistant for Web Dev & Cybersecurity updates
            (SQLite + Chroma + MiniLM + OSS Llama 3.1 via Groq).
          </p>
        </header>

        {/* Query card */}
        <section className="rounded-2xl border border-slate-800 bg-slate-900/60 p-4 shadow-xl shadow-slate-950/60 backdrop-blur">
          <label
            htmlFor="query"
            className="mb-2 block text-xs font-medium uppercase tracking-wide text-slate-300"
          >
            Question
          </label>
          <textarea
            id="query"
            className="w-full rounded-xl border border-slate-700 bg-slate-950/80 px-3 py-2 text-sm text-slate-100 shadow-inner shadow-black/60 outline-none focus:border-emerald-400 focus:ring-1 focus:ring-emerald-400"
            rows={3}
            placeholder='e.g. "Any major security vulnerabilities or breaches recently?"'
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={handleKeyDown}
          />

          <div className="mt-3 flex flex-wrap gap-3">
            <div className="flex flex-col text-xs">
              <span className="mb-1 font-medium text-slate-300">Topic</span>
              <select
                className="rounded-lg border border-slate-700 bg-slate-950/80 px-2 py-1 text-xs text-slate-100 focus:border-emerald-400 focus:outline-none focus:ring-1 focus:ring-emerald-400"
                value={topic}
                onChange={(e) => setTopic(e.target.value as Topic)}
              >
                <option value="all">All</option>
                <option value="webdev">Web Dev</option>
                <option value="cybersec">Cybersecurity</option>
              </select>
            </div>

            <div className="flex flex-col text-xs">
              <span className="mb-1 font-medium text-slate-300">
                Max articles (k)
              </span>
              <input
                type="number"
                min={1}
                max={15}
                value={k}
                onChange={(e) => setK(Number(e.target.value) || 6)}
                className="w-20 rounded-lg border border-slate-700 bg-slate-950/80 px-2 py-1 text-xs text-slate-100 focus:border-emerald-400 focus:outline-none focus:ring-1 focus:ring-emerald-400"
              />
            </div>

            <div className="flex flex-1 items-end justify-end">
              <button
                onClick={handleAsk}
                disabled={loading}
                className="inline-flex items-center justify-center rounded-xl bg-emerald-400 px-3 py-1.5 text-xs font-semibold text-emerald-950 shadow-md shadow-emerald-500/40 transition hover:bg-emerald-300 disabled:cursor-not-allowed disabled:opacity-60"
              >
                {loading ? "Thinking…" : "Ask DevSec Brief"}
              </button>
            </div>
          </div>

          <p className="mt-2 text-[11px] text-slate-500">
            Tip: Press <span className="font-mono">⌘+Enter</span> /
            <span className="font-mono">Ctrl+Enter</span> to send quickly.
          </p>

          {error && (
            <p className="mt-2 text-xs text-rose-400">
              {error}
            </p>
          )}
        </section>

        {/* Answer + sources */}
        {(answer || sources.length > 0) && (
          <section className="mt-6 space-y-4">
            <div className="rounded-2xl border border-slate-800 bg-slate-900/70 p-4 shadow-lg shadow-slate-950/50">
              <h2 className="mb-2 text-sm font-semibold text-slate-100">
                Answer
              </h2>
              <pre className="whitespace-pre-wrap text-sm text-slate-200">
                {answer || "(no answer returned)"}
              </pre>
            </div>

            <div className="rounded-2xl border border-slate-800 bg-slate-900/70 p-4 shadow-lg shadow-slate-950/50">
              <h2 className="mb-3 text-sm font-semibold text-slate-100">
                Sources
              </h2>
              {sources.length === 0 ? (
                <p className="text-xs text-slate-500">No sources returned.</p>
              ) : (
                <ul className="space-y-2 text-xs">
                  {sources.map((s, idx) => (
                    <li key={idx} className="rounded-lg border border-slate-800 bg-slate-950/60 p-2">
                      <div className="mb-1 flex flex-wrap items-center gap-2">
                        {s.category && (
                          <span className="rounded-full bg-slate-800 px-2 py-0.5 text-[10px] uppercase tracking-wide text-slate-300">
                            {s.category}
                          </span>
                        )}
                        {s.source && (
                          <span className="text-[11px] text-slate-400">
                            {s.source}
                          </span>
                        )}
                      </div>
                      <div className="text-slate-100">
                        {s.title || "(no title)"}
                      </div>
                      {s.url && (
                        <a
                          href={s.url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="mt-1 inline-block text-[11px] text-sky-400 hover:underline"
                        >
                          {s.url}
                        </a>
                      )}
                      {s.published_at && (
                        <div className="mt-1 text-[10px] text-slate-500">
                          Published: {s.published_at}
                        </div>
                      )}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </section>
        )}
      </div>
    </main>
  );
}
