"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { api, askStream } from "@/lib/api";
import type { Citation, Evidence, Message, ResearchEvent } from "@/lib/types";
import { Answer } from "./Answer";

interface Live {
  route?: string;
  plan: string[];
  done: { step: string; documents: number }[];
  evidence?: Evidence;
}

const EMPTY: Live = { plan: [], done: [] };

export function Chat({ threadId }: { threadId: string }) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [question, setQuestion] = useState("");
  const [steps, setSteps] = useState(3);
  const [running, setRunning] = useState(false);
  const [live, setLive] = useState<Live>(EMPTY);
  const [error, setError] = useState("");
  const abort = useRef<AbortController | null>(null);

  const refresh = useCallback(async () => {
    try {
      setMessages(await api.listMessages(threadId));
    } catch (e) {
      setError((e as Error).message);
    }
  }, [threadId]);

  useEffect(() => {
    refresh();
    return () => abort.current?.abort();
  }, [refresh]);

  async function ask(event: React.FormEvent) {
    event.preventDefault();
    const asked = question.trim();
    if (!asked) return;

    setRunning(true);
    setError("");
    setLive(EMPTY);
    setQuestion("");
    setMessages((prior) => [
      ...prior,
      {
        id: `pending-${Date.now()}`,
        thread_id: threadId,
        role: "user",
        content: asked,
        plan: [],
        citations: [],
        evidence: {},
        created_at: new Date().toISOString(),
      },
    ]);

    const controller = new AbortController();
    abort.current = controller;

    try {
      await askStream(
        threadId,
        { question: asked, max_research_steps: steps },
        (event: ResearchEvent) => {
          switch (event.type) {
            case "routed":
              setLive((p) => ({ ...p, route: event.route }));
              break;
            case "plan":
              setLive((p) => ({ ...p, plan: event.steps }));
              break;
            case "step_complete":
              setLive((p) => ({
                ...p,
                done: [
                  ...p.done,
                  { step: event.step, documents: event.document_count },
                ],
              }));
              break;
            case "evidence":
              setLive((p) => ({
                ...p,
                evidence: {
                  sufficient: event.sufficient,
                  reason: event.reason,
                  missing: event.missing,
                },
              }));
              break;
            case "error":
              setError(event.message);
              break;
          }
        },
        controller.signal,
      );
      await refresh();
      setLive(EMPTY);
    } catch (e) {
      if ((e as Error).name !== "AbortError") setError((e as Error).message);
    } finally {
      setRunning(false);
      abort.current = null;
    }
  }

  return (
    <>
      {messages.map((m) =>
        m.role === "user" ? (
          <div className="bubble" key={m.id}>
            {m.content}
          </div>
        ) : (
          <Turn key={m.id} message={m} />
        ),
      )}

      {running && <LivePipeline live={live} />}
      {error && <p className="notice">{error}</p>}

      <form className="composer" onSubmit={ask}>
        <input
          placeholder="Ask a follow-up research question…"
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          disabled={running}
        />
        <select
          className="select"
          value={steps}
          onChange={(e) => setSteps(Number(e.target.value))}
          disabled={running}
          title="Research steps"
        >
          {[1, 2, 3, 4, 5].map((n) => (
            <option key={n} value={n}>
              {n} step{n === 1 ? "" : "s"}
            </option>
          ))}
        </select>
        {running ? (
          <button
            type="button"
            className="btn-send"
            onClick={() => abort.current?.abort()}
          >
            Stop
          </button>
        ) : (
          <button type="submit" className="btn-send" disabled={!question.trim()}>
            Send
          </button>
        )}
      </form>
    </>
  );
}

/** A completed assistant turn: plan, evidence, then the answer. */
function Turn({ message }: { message: Message }) {
  const citations = (message.citations ?? []) as Citation[];
  const abstained = message.evidence?.sufficient === false;
  const plan = message.plan ?? [];

  return (
    <div className="pipeline">
      {plan.length > 0 && (
        <>
          <div className="stage">
            <span className="eyebrow kicker">Research Plan</span>
            <div className="tasks">
              <div className="tasks-head">Tasks</div>
              {plan.map((step, i) => (
                <div className="task" data-state="done" key={i}>
                  <span className="task-mark">✓</span>
                  <span className="task-label">{step}</span>
                  <span className="task-status">done</span>
                </div>
              ))}
            </div>
          </div>
          <Connector />
        </>
      )}

      {citations.length > 0 && (
        <>
          <div className="stage">
            <span className="eyebrow eyebrow-ok">Evidence</span>
            <EvidenceGrid citations={citations} />
          </div>
          <Connector />
        </>
      )}

      <div className="stage" style={{ gap: 10 }}>
        <span className="eyebrow eyebrow-answer">
          {abstained ? "No answer" : "Answer"}
        </span>
        {abstained ? (
          <div className="abstained">
            <div className="abstained-label">Abstained</div>
            <div style={{ marginTop: 8 }}>
              <Answer text={message.content} />
            </div>
          </div>
        ) : (
          <Answer text={message.content} />
        )}
      </div>
    </div>
  );
}

function EvidenceGrid({ citations }: { citations: Citation[] }) {
  return (
    <div className="evidence-grid">
      {citations.map((c) => (
        <div className="evidence" data-resolved={c.resolved} key={c.number}>
          <div className="evidence-head">
            <span className="evidence-ref">[{c.number}]</span>
            <span className="evidence-source" title={c.source}>
              {c.resolved ? (
                c.url ? (
                  <a className="link" href={c.url} target="_blank" rel="noreferrer">
                    {c.title}
                  </a>
                ) : (
                  c.title
                )
              ) : (
                "cites no retrieved document"
              )}
            </span>
          </div>
          {c.snippet && <p className="evidence-snippet">{c.snippet}</p>}
        </div>
      ))}
    </div>
  );
}

/** The workflow as it happens, so a long run is not a blank screen. */
function LivePipeline({ live }: { live: Live }) {
  const finished = new Set(live.done.map((d) => d.step));
  const firstPending = live.plan.find((s) => !finished.has(s));

  return (
    <div className="pipeline">
      <div className="stage">
        <span className="eyebrow kicker">Research Plan</span>
        <p className="stage-body">
          {live.plan.length === 0
            ? live.route
              ? `Routed as ${live.route}. Planning…`
              : "Reading the question…"
            : `Running ${live.plan.length} research task${
                live.plan.length === 1 ? "" : "s"
              } in parallel.`}
        </p>
      </div>

      {live.plan.length > 0 && (
        <>
          <Connector />
          <div className="tasks">
            <div className="tasks-head">Tasks</div>
            {live.plan.map((step, i) => {
              const done = live.done.find((d) => d.step === step);
              const state = done
                ? "done"
                : step === firstPending
                  ? "active"
                  : "queued";
              return (
                <div className="task" data-state={state} key={i}>
                  <span className="task-mark">{done ? "✓" : ""}</span>
                  <span className="task-label">{step}</span>
                  <span className="task-status">
                    {done ? `${done.documents} passages` : state}
                  </span>
                </div>
              );
            })}
          </div>
        </>
      )}

      {live.evidence && (
        <>
          <Connector />
          <div className="stage">
            <span className="eyebrow eyebrow-ok">Evidence</span>
            <p className="stage-body">
              {live.evidence.sufficient
                ? "Sufficient — writing the answer…"
                : `Insufficient. ${live.evidence.missing}`}
            </p>
          </div>
        </>
      )}
    </div>
  );
}

function Connector() {
  return (
    <svg width="2" height="26" className="connector" aria-hidden="true">
      <line
        x1="1"
        y1="0"
        x2="1"
        y2="26"
        stroke="var(--idle)"
        strokeWidth="1.4"
        strokeDasharray="1 4"
        strokeLinecap="round"
      />
    </svg>
  );
}
