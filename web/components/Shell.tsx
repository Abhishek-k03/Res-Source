"use client";

import { useParams, useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { api } from "@/lib/api";
import type { Collection, Thread } from "@/lib/types";

/**
 * Persistent sidebar plus the routed page beside it.
 *
 * Collections and History are refetched on navigation, so creating either from
 * a page shows up here without a manual refresh.
 */
export function Shell({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const params = useParams<{ id?: string; threadId?: string }>();
  const collectionId = params?.id;
  const threadId = params?.threadId;

  const [collections, setCollections] = useState<Collection[]>([]);
  const [threads, setThreads] = useState<Thread[]>([]);
  const [health, setHealth] = useState<"ok" | "degraded" | "down">("down");
  const [starting, setStarting] = useState(false);

  const refresh = useCallback(async () => {
    try {
      setCollections(await api.listCollections());
    } catch {
      setCollections([]);
    }
    if (!collectionId) {
      setThreads([]);
      return;
    }
    try {
      setThreads(await api.listThreads(collectionId));
    } catch {
      setThreads([]);
    }
  }, [collectionId]);

  useEffect(() => {
    refresh();
  }, [refresh, threadId]);

  useEffect(() => {
    api
      .health()
      .then((h) => setHealth(h.status === "ok" ? "ok" : "degraded"))
      .catch(() => setHealth("down"));
  }, []);

  async function removeThread(thread: Thread) {
    if (!confirm(`Delete "${thread.title}"?`)) return;
    try {
      await api.deleteThread(thread.id);
    } catch (e) {
      alert((e as Error).message);
      return;
    }
    // Leave the thread if it is the one on screen, otherwise just relist.
    if (thread.id === threadId) {
      router.push(`/collections/${thread.collection_id}`);
    } else {
      await refresh();
    }
  }

  async function newResearch() {
    const target = collectionId ?? collections[0]?.id;
    if (!target) {
      router.push("/collections/new");
      return;
    }
    setStarting(true);
    try {
      const thread = await api.createThread(target);
      router.push(`/collections/${target}/threads/${thread.id}`);
    } finally {
      setStarting(false);
    }
  }

  const healthColor =
    health === "ok"
      ? "var(--ok)"
      : health === "degraded"
        ? "oklch(72% 0.09 80)"
        : "var(--bad)";

  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand">
          <svg width="20" height="20" viewBox="0 0 20 20" style={{ flex: "none" }}>
            <path
              d="M4 3 L4 17 M4 3 L14 3 M4 10 L11 10"
              stroke="var(--accent)"
              strokeWidth="1.6"
              fill="none"
              strokeLinecap="round"
            />
          </svg>
          <span className="brand-name">Res-Source</span>
        </div>

        <button className="btn" onClick={newResearch} disabled={starting}>
          <span style={{ fontSize: 15, lineHeight: 1 }}>+</span>
          {starting ? "Starting…" : "New research"}
        </button>

        <div className="nav-group">
          <div className="nav-head">
            <span className="eyebrow">Collections</span>
            <button
              className="nav-add"
              onClick={() => router.push("/collections/new")}
            >
              + New
            </button>
          </div>
          {collections.length === 0 ? (
            <div className="nav-empty">None yet</div>
          ) : (
            collections.map((c) => (
              <button
                key={c.id}
                className="nav-item"
                data-active={c.id === collectionId}
                onClick={() => router.push(`/collections/${c.id}`)}
              >
                <span className="dot" />
                <span className="truncate">{c.name}</span>
              </button>
            ))
          )}
        </div>

        <div className="nav-group">
          <div className="nav-head">
            <span className="eyebrow">History</span>
          </div>
          {threads.length === 0 ? (
            <div className="nav-empty">
              {collectionId ? "No conversations" : "Select a collection"}
            </div>
          ) : (
            threads.map((t) => (
              <div className="nav-row" key={t.id}>
                <button
                  className="nav-item"
                  data-active={t.id === threadId}
                  onClick={() =>
                    router.push(`/collections/${t.collection_id}/threads/${t.id}`)
                  }
                >
                  <span className="truncate">{t.title}</span>
                </button>
                <button
                  className="nav-del"
                  title="Delete conversation"
                  aria-label={`Delete conversation: ${t.title}`}
                  onClick={() => removeThread(t)}
                >
                  ×
                </button>
              </div>
            ))
          )}
        </div>

        <div className="sidebar-foot">
          <span className="status-dot" style={{ background: healthColor }} />
          <span style={{ fontSize: 12.5, color: "var(--text-muted)" }}>
            {health === "ok"
              ? "All services healthy"
              : health === "degraded"
                ? "Service degraded"
                : "API unreachable"}
          </span>
        </div>
      </aside>

      {children}
    </div>
  );
}
