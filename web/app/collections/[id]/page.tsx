"use client";

import { useRouter } from "next/navigation";
import { use, useEffect, useState } from "react";

import { SourcePanel } from "@/components/SourcePanel";
import { api } from "@/lib/api";
import type { Collection } from "@/lib/types";

export default function CollectionPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  const router = useRouter();
  const [collection, setCollection] = useState<Collection | null>(null);
  const [error, setError] = useState("");
  const [starting, setStarting] = useState(false);

  useEffect(() => {
    api
      .getCollection(id)
      .then(setCollection)
      .catch((e) => setError((e as Error).message));
  }, [id]);

  async function research() {
    setStarting(true);
    try {
      const thread = await api.createThread(id);
      router.push(`/collections/${id}/threads/${thread.id}`);
    } catch (e) {
      setError((e as Error).message);
      setStarting(false);
    }
  }

  async function remove() {
    if (!collection) return;
    if (
      !confirm(
        `Delete "${collection.name}"? This removes its sources, conversations, and indexed vectors.`,
      )
    )
      return;
    try {
      await api.deleteCollection(collection.id);
      router.push("/");
    } catch (e) {
      setError((e as Error).message);
    }
  }

  if (error && !collection) return <main className="main"><p className="notice">{error}</p></main>;
  if (!collection) return <main className="main"><p className="muted">Loading…</p></main>;

  return (
    <main className="main main-narrow">
      <div className="page-head">
        <span className="kicker">Collection</span>
        <h1 className="title">{collection.name}</h1>
        <p className="lede">
          <span className="mono">{collection.slug}</span> ·{" "}
          {collection.research_domain}
        </p>
      </div>

      <SourcePanel collectionId={collection.id} />

      <div className="actions">
        <button className="btn btn-ghost" onClick={remove}>
          Delete collection
        </button>
        <button className="btn btn-primary" onClick={research} disabled={starting}>
          {starting ? "Starting…" : "Start research"}
        </button>
      </div>
    </main>
  );
}
