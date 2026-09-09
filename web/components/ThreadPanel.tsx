"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";

import { api } from "@/lib/api";
import type { Thread } from "@/lib/types";

export function ThreadPanel({ collectionId }: { collectionId: string }) {
  const router = useRouter();
  const [threads, setThreads] = useState<Thread[]>([]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const refresh = useCallback(async () => {
    try {
      setThreads(await api.listThreads(collectionId));
    } catch (e) {
      setError((e as Error).message);
    }
  }, [collectionId]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  async function start() {
    setBusy(true);
    try {
      const thread = await api.createThread(collectionId);
      router.push(`/collections/${collectionId}/threads/${thread.id}`);
    } catch (e) {
      setError((e as Error).message);
      setBusy(false);
    }
  }

  async function remove(thread: Thread) {
    if (!confirm("Delete this conversation?")) return;
    try {
      await api.deleteThread(thread.id);
      await refresh();
    } catch (e) {
      setError((e as Error).message);
    }
  }

  return (
    <section>
      <h2>Conversations</h2>
      {error && <p className="error">{error}</p>}

      <p>
        <button onClick={start} disabled={busy}>
          {busy ? "Starting…" : "New conversation"}
        </button>
      </p>

      {threads.length === 0 ? (
        <p className="muted">No conversations yet.</p>
      ) : (
        threads.map((t) => (
          <div className="card" key={t.id}>
            <div className="row" style={{ justifyContent: "space-between" }}>
              <Link href={`/collections/${collectionId}/threads/${t.id}`}>
                {t.title}
              </Link>
              <button onClick={() => remove(t)}>Delete</button>
            </div>
          </div>
        ))
      )}
    </section>
  );
}
