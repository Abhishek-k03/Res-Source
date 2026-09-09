"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { api } from "@/lib/api";
import type { Job, JobStatus, Source } from "@/lib/types";

const POLL_MS = 2000;
const ACCEPT = ".pdf,.md,.markdown,.txt,.html,.htm";

/** Design pill vocabulary, mapped onto the API's job statuses. */
const PILL: Record<JobStatus, { label: string; cls: string }> = {
  completed: { label: "ready", cls: "pill-ready" },
  processing: { label: "parsing", cls: "pill-parsing" },
  pending: { label: "queued", cls: "pill-queued" },
  failed: { label: "error", cls: "pill-error" },
};

const GLYPH: Record<Source["kind"], string> = {
  files: "▤",
  urls: "◧",
  arxiv: "◇",
};

function meta(source: Source): string {
  if (source.status === "failed") return source.error || "failed to ingest";
  if (source.status === "completed") {
    const n = source.chunk_count;
    return `${n} chunk${n === 1 ? "" : "s"} · indexed`;
  }
  const job: Job | null = source.latest_job;
  const stage = job?.status === "processing" ? job.stage : "queued";
  const chunks = job?.chunk_count ? ` · ${job.chunk_count} chunks` : "";
  return `${source.kind} · ${stage}${chunks}`;
}

export function SourcePanel({ collectionId }: { collectionId: string }) {
  const [sources, setSources] = useState<Source[]>([]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [over, setOver] = useState(false);
  const [kind, setKind] = useState<"arxiv" | "urls">("urls");
  const [locator, setLocator] = useState("");
  const fileInput = useRef<HTMLInputElement>(null);

  const refresh = useCallback(async () => {
    try {
      setSources(await api.listSources(collectionId));
    } catch (e) {
      setError((e as Error).message);
    }
  }, [collectionId]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  // Ingestion is asynchronous, so poll only while something is in flight.
  const active = sources.some(
    (s) => s.status === "pending" || s.status === "processing",
  );
  useEffect(() => {
    if (!active) return;
    const timer = setInterval(refresh, POLL_MS);
    return () => clearInterval(timer);
  }, [active, refresh]);

  const upload = useCallback(
    async (files: File[]) => {
      if (files.length === 0) return;
      setBusy(true);
      setError("");
      try {
        for (const file of files) {
          await api.uploadSource(collectionId, file);
        }
        await refresh();
      } catch (e) {
        setError((e as Error).message);
      } finally {
        setBusy(false);
        if (fileInput.current) fileInput.current.value = "";
      }
    },
    [collectionId, refresh],
  );

  async function add(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      await api.addSource(collectionId, { kind, locator: locator.trim() });
      setLocator("");
      await refresh();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function act(source: Source, what: "reindex" | "delete") {
    if (what === "delete" && !confirm(`Delete "${source.title}" and its chunks?`))
      return;
    try {
      if (what === "reindex") await api.reindexSource(source.id);
      else await api.deleteSource(source.id);
      await refresh();
    } catch (e) {
      setError((e as Error).message);
    }
  }

  return (
    <>
      {error && <p className="notice">{error}</p>}

      <div
        className="dropzone"
        data-over={over}
        onDragOver={(e) => {
          e.preventDefault();
          setOver(true);
        }}
        onDragLeave={() => setOver(false)}
        onDrop={(e) => {
          e.preventDefault();
          setOver(false);
          upload(Array.from(e.dataTransfer.files));
        }}
      >
        <svg width="26" height="26" viewBox="0 0 26 26">
          <path
            d="M13 4 L13 17 M7 10 L13 4 L19 10 M5 20 L21 20"
            stroke="oklch(62% 0.006 255)"
            strokeWidth="1.6"
            fill="none"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
        <span className="dropzone-hint">
          Drag files here, or{" "}
          <span className="link" onClick={() => fileInput.current?.click()}>
            browse
          </span>
        </span>
        <span className="dropzone-formats">PDF, Markdown, TXT, HTML</span>
        <input
          ref={fileInput}
          type="file"
          multiple
          accept={ACCEPT}
          hidden
          onChange={(e) => upload(Array.from(e.target.files ?? []))}
        />
      </div>

      <form className="field" onSubmit={add}>
        <label className="label">Add by URL or arXiv query</label>
        <div className="row">
          <select
            className="select"
            value={kind}
            onChange={(e) => setKind(e.target.value as "arxiv" | "urls")}
          >
            <option value="urls">URL</option>
            <option value="arxiv">arXiv</option>
          </select>
          <input
            className="input grow"
            placeholder={
              kind === "urls"
                ? "https://arxiv.org/abs/2004.05074"
                : "raft consensus algorithm"
            }
            value={locator}
            onChange={(e) => setLocator(e.target.value)}
            required
          />
          <button
            type="submit"
            className="btn btn-quiet"
            disabled={busy || !locator.trim()}
          >
            Add
          </button>
        </div>
      </form>

      <div className="field">
        <label className="label">Sources ({sources.length})</label>
        <div className="list">
          {sources.length === 0 ? (
            <div className="list-empty">
              No sources yet. Questions will abstain until you add one.
            </div>
          ) : (
            sources.map((s) => {
              const pill = PILL[s.status];
              return (
                <div className="list-row" key={s.id}>
                  <span className="list-glyph">{GLYPH[s.kind]}</span>
                  <div className="list-body">
                    <div className="list-name">{s.title}</div>
                    <div className="list-meta">{meta(s)}</div>
                  </div>
                  <span className="row-actions">
                    <button
                      className="btn-mini"
                      onClick={() => act(s, "reindex")}
                      disabled={busy}
                    >
                      Re-index
                    </button>
                    <button
                      className="btn-mini"
                      onClick={() => act(s, "delete")}
                      disabled={busy}
                    >
                      Delete
                    </button>
                  </span>
                  <span className={`pill ${pill.cls}`}>{pill.label}</span>
                </div>
              );
            })
          )}
        </div>
      </div>
    </>
  );
}
