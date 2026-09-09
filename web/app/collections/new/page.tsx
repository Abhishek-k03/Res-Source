"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { api } from "@/lib/api";

/** Turn a display name into an API-acceptable slug. */
function toSlug(name: string): string {
  return name
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 63);
}

export default function NewCollectionPage() {
  const router = useRouter();
  const [name, setName] = useState("");
  const [domain, setDomain] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const slug = toSlug(name);

  async function create(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const collection = await api.createCollection({
        slug,
        name: name.trim(),
        research_domain: domain.trim() || "the indexed research corpus",
      });
      router.push(`/collections/${collection.id}`);
    } catch (e) {
      setError((e as Error).message);
      setBusy(false);
    }
  }

  return (
    <main className="main main-narrow">
      <div className="page-head">
        <span className="kicker">New Collection</span>
        <h1 className="title">Create a research collection</h1>
        <p className="lede">
          Ingest sources once, then ask questions against this collection.
          Accepts PDFs, Markdown, text, HTML, web URLs, and arXiv queries.
        </p>
      </div>

      {error && <p className="notice">{error}</p>}

      <form className="main-narrow" style={{ display: "contents" }} onSubmit={create}>
        <div className="field">
          <label className="label">Collection name</label>
          <input
            className="input"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Sleep & Memory Consolidation"
            required
            autoFocus
          />
          {slug && (
            <span className="mono" style={{ color: "var(--text-fainter)" }}>
              {slug}
            </span>
          )}
        </div>

        <div className="field">
          <label className="label">Research domain</label>
          <input
            className="input"
            value={domain}
            onChange={(e) => setDomain(e.target.value)}
            placeholder="what this corpus is about — it steers routing and answering"
          />
        </div>

        <p className="lede">
          Sources are added on the next screen, once the collection exists.
        </p>

        <div className="actions">
          <button
            type="button"
            className="btn btn-ghost"
            onClick={() => router.push("/")}
          >
            Cancel
          </button>
          <button
            type="submit"
            className="btn btn-primary"
            disabled={busy || !slug}
          >
            {busy ? "Creating…" : "Create collection"}
          </button>
        </div>
      </form>
    </main>
  );
}
