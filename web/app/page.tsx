"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { api } from "@/lib/api";
import type { Collection } from "@/lib/types";

export default function CollectionsPage() {
  const [collections, setCollections] = useState<Collection[]>([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api
      .listCollections()
      .then(setCollections)
      .catch((e) => setError((e as Error).message))
      .finally(() => setLoading(false));
  }, []);

  return (
    <main className="main main-narrow">
      <div className="page-head">
        <span className="kicker">Workspace</span>
        <h1 className="title">Collections</h1>
        <p className="lede">
          Each collection is an isolated corpus. Ingest sources once, then ask
          questions answered only from what it contains.
        </p>
      </div>

      {error && <p className="notice">{error}</p>}

      {loading ? (
        <p className="muted">Loading…</p>
      ) : collections.length === 0 ? (
        <div className="dropzone" style={{ padding: "44px 20px" }}>
          <span className="dropzone-hint">No collections yet.</span>
          <Link className="btn btn-primary" href="/collections/new">
            Create a collection
          </Link>
        </div>
      ) : (
        <div className="card-grid">
          {collections.map((c) => (
            <Link className="collection-card" href={`/collections/${c.id}`} key={c.id}>
              <h3>{c.name}</h3>
              <div className="mono" style={{ color: "var(--text-fainter)" }}>
                {c.slug}
              </div>
              <div className="muted">
                {c.source_count} source{c.source_count === 1 ? "" : "s"} ·{" "}
                {c.research_domain}
              </div>
            </Link>
          ))}
        </div>
      )}
    </main>
  );
}
