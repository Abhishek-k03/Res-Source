# Design context — Research Agent

**What it is.** A research assistant that answers questions strictly from a corpus
you build yourself. It plans a question into several research tasks, runs them in
parallel, and returns a cited answer — or refuses when the corpus cannot support
one. The differentiator is that the *work is visible*: users watch it think.

**Who uses it.** Engineers and researchers building a private knowledge base.
Tone: precise, calm, technical. Not chatty, no mascot, no emoji.

## Screens

1. **Collections** — isolated corpora (name, slug, source count, research domain).
   Create form; delete. Backend health indicator. Typically 1–10 collections.
2. **Collection detail** — two regions: *Sources* (upload PDF/Markdown/text/HTML,
   or add an arXiv query or URL) and *Conversations*. Expect 3–30 sources.
3. **Research thread** — the centrepiece. Message history plus a composer with a
   "research steps" control (1–5, default 3).

## Signature moments

**Live research progress.** While answering, the UI streams: routed → plan created
→ each task completing *out of order* with a passage count → evidence verdict →
answer. This should feel like watching a process, not a spinner. Real plan step:
*"Describe how Raft handles leader election compared to Paxos."* Steps are one
sentence, occasionally two lines.

**Citations.** Answers carry inline `[1]` markers resolved to real documents —
title, file path, sometimes a URL. Typical answer: 3–6 short paragraphs or bullets,
150–350 words, with 1–8 citations often repeating the same 2–3 documents. A marker
resolving to nothing must render as a visible warning, never be hidden.

**Refusal.** When evidence is insufficient the assistant abstains, cites nothing,
and names what to add: *"The search returned documents on replication, quorums,
CAP, Paxos, Raft and failure detection, but none on Kafka consumer groups."*
Design this as a legitimate outcome, not an error.

**Ingestion stages.** Sources show `queued → loading → splitting → indexing → done`
with live chunk counts. Jobs run concurrently, three at a time.

## Real dimensions

- Research takes **12–30s**. Long enough that progress matters, short enough that
  users wait rather than leave.
- Ingestion ranges from **seconds** (small Markdown, 2–8 chunks) to **~2 minutes**
  (a large PDF, 150+ chunks). Sources poll only while work is in flight.
- Assistant messages carry three extras: the plan, resolved citations, and the
  evidence verdict. Only the answer and citations deserve prominence — the plan is
  secondary, collapsible.
- Source titles vary in shape: `raft-consensus.md`, a full arXiv paper title, or a
  bare URL. Long ones must truncate gracefully.

## States to cover

Empty collection, empty thread, ingesting, ingestion failed (with retry and an
error message), research running, stream error, unreachable API, refusal.

**Constraints.** No authentication or user accounts, so no avatars, profiles, or
sharing. Desktop-first; usable at tablet width. Light and dark. Answers arrive as
one block, not token-by-token — do not design a typewriter effect.
