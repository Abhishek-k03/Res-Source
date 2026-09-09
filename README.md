# Research RAG Agent

A retrieval-augmented research agent built with **LangChain** and **LangGraph**. It
ingests a corpus from local files, arXiv, or the web into **Elasticsearch**, then
answers questions about it by planning a short research strategy, searching from
several angles in parallel, and writing an answer that cites what it actually read.

Structured as two LangGraph graphs behind a FastAPI service, with a Redis-backed
worker doing ingestion off the request path. Runnable from the CLI, from
LangGraph Studio, or over HTTP.

```
Next.js ──> FastAPI ──> LangGraph ──> Elasticsearch   (vectors)
                │
                ├──> Postgres    collections, sources, jobs, conversations
                └──> Redis ──> worker ──> ingest graph
```

## How it works

**Ingest graph** — builds the corpus.

```
load_documents ──> split_documents ──> index_documents ──> prune_stale_chunks
 (files│arxiv│urls)  (chunk + overlap)  (embed → Elasticsearch)  (drop superseded)
```

**Research graph** — answers questions.

```
analyze_and_route_query ─┬─> ask_for_more_info ───────────────────> END
                         ├─> respond_to_general_query ────────────> END
                         └─> create_research_plan
                                    │
                              (fan out, one task per plan step)
                                    ↓
                             conduct_research ×N
                                    ↓
                             assess_evidence ─┬─> respond ──> END
                                              └─> abstain ──> END
```

Every plan step is dispatched at once, and each runs the **researcher subgraph**,
which fans out again over several rewritten queries:

```
generate_queries ──> retrieve_documents ×N  (parallel fan-out, one per query)
```

So a 3-step plan with 3 queries per step is 9 concurrent retrievals, not 3 rounds
of 3. Steps are written to be independent, so nothing is gained by serialising
them.

Five things this buys over a plain `retrieve → stuff → answer` chain:

- **Routing.** Small talk and under-specified questions never reach the vector
  store. An unanswerable question gets a follow-up question, not a hallucination.
- **Query expansion.** One research step becomes several differently-worded
  searches, so a document is found even when the user's vocabulary does not match
  the corpus. This is the single biggest win in most RAG systems.
- **De-duplication.** Parallel queries and multi-step plans retrieve overlapping
  chunks constantly; `reduce_docs` hashes content so the answer prompt sees each
  passage once.
- **Abstention as a decision, not a hope.** `assess_evidence` is a gate before
  synthesis: retrieving nothing abstains without an LLM call at all, and
  otherwise a structured call judges whether the passages can support an answer.
  A prompt asking a model to admit ignorance is a request; this is a branch.
- **Resolved citations.** The `[n]` markers the model writes are mapped back onto
  the metadata of the documents actually retrieved, so a citation carries a real
  title, source, and URL -- and one pointing past the evidence is reported rather
  than silently trusted.

## Setup

**Prerequisites:** Python 3.10+, Docker, and a [Groq API key](https://console.groq.com/keys) (free tier is fine).

```bash
cd research-agent
python -m venv .venv
.venv\Scripts\activate          # Windows;  source .venv/bin/activate on macOS/Linux
pip install -e ".[dev]"

copy .env.example .env          # cp on macOS/Linux -- then add your GROQ_API_KEY
docker compose up -d            # Elasticsearch, Postgres, and Redis
```

Groq serves chat models only, not embeddings, so the two are independent: the LLM
calls go to Groq and embeddings stay local on fastembed.

Postgres and Redis are published on **5434** and **6380**, not their defaults, so
they do not collide with anything already running locally.

Embeddings run **locally** via
[fastembed](https://github.com/qdrant/fastembed) (`BAAI/bge-small-en-v1.5`, ONNX,
~130 MB on first use), which keeps ingestion free and offline — a few thousand
chunks would otherwise be a few thousand API calls. Groq has no embedding
endpoint, so to change embedding provider you would point `embedding_model` at
`openai/…`, `cohere/…`, or `google/gemini-embedding-001` and supply that key.
Switching means re-indexing into a fresh `index_name`.

## Use it

Index something, then ask about it:

```bash
# Local PDFs, Markdown, text, HTML -- put them in data/
python scripts/ingest.py files --dir data

# Papers from arXiv -- downloads and parses each PDF by default;
# add --abstracts-only for a fast, shallow survey
python scripts/ingest.py arxiv "retrieval augmented generation" --max 8

# Web pages
python scripts/ingest.py urls https://arxiv.org/abs/2005.11401

# Ask a question
python scripts/ask.py "What problem does retrieval augmentation solve?" \
    --domain "retrieval-augmented generation research"

# Or hold a conversation, with the previous turns remembered
python scripts/ask.py --chat --domain "retrieval-augmented generation research"
```

Shared flags (`--index-name`, `--embedding-model`, `--chunk-size`,
`--chunk-overlap`) go **after** the source name.

`--domain` is worth setting. It is interpolated into every prompt, and it is how
the router knows what counts as on-topic and what counts as small talk.

### As a service

```bash
uvicorn api.main:app --reload --port 8000   # API on http://localhost:8000/docs
python -m api.worker                        # ingestion worker, in a second shell
```

Adding a source returns `202` immediately and queues a job; the worker runs the
ingest graph and writes status back to Postgres. One worker runs
`WORKER_CONCURRENCY` jobs at a time (default 3), so queueing several sources
ingests them together rather than one behind the other. Loaders and the splitter
run in worker threads, so a slow PDF download cannot stall the other jobs.

```bash
BASE=http://localhost:8000

curl -X POST $BASE/collections -H 'Content-Type: application/json'   -d '{"slug":"distsys","name":"Distributed Systems","research_domain":"distributed consensus"}'

curl -X POST $BASE/collections/distsys/sources/upload -F 'file=@raft.pdf'
curl -X POST $BASE/collections/distsys/sources -H 'Content-Type: application/json'   -d '{"kind":"arxiv","locator":"raft consensus"}'

curl $BASE/collections/distsys/sources          # watch status reach "completed"

THREAD=$(curl -sX POST $BASE/collections/distsys/threads   -H 'Content-Type: application/json' -d '{}' | jq -r .id)
curl -N -X POST $BASE/threads/$THREAD/ask -H 'Content-Type: application/json'   -d '{"question":"How does Raft elect a leader?"}'
```

The last call streams server-sent events as the workflow runs:

```
data: {"type": "routed", "route": "research"}
data: {"type": "plan", "steps": ["How does Raft handle leader election..."]}
data: {"type": "step_complete", "step": "...", "document_count": 4}
data: {"type": "evidence", "sufficient": true, "reason": "..."}
data: {"type": "answer", "content": "...", "citations": [...]}
data: {"type": "done"}
```

Only workflow milestones are streamed — never raw model reasoning. Each answer is
persisted with its plan, resolved citations, and evidence verdict, so a
conversation can be replayed from `GET /threads/{id}/messages`.

### The web interface

With the API and worker running, start the frontend in a third shell:

```bash
cd web
npm install
cp .env.local.example .env.local    # NEXT_PUBLIC_API_URL, defaults to :8000
npm run dev                         # http://localhost:3000
```

Three pages, deliberately unstyled:

| Page | What it does |
| --- | --- |
| `/` | Create, list, and delete collections; shows API health |
| `/collections/[id]` | Add sources (upload, arXiv, URL) with live ingestion stages; list conversations |
| `/collections/[id]/threads/[threadId]` | Ask questions, watch the workflow stream, read cited answers |

The source list polls only while an ingestion is in flight, and renders the
worker's stage (`loading → splitting → indexing`) rather than a bare spinner.
The research page streams the plan and each finished task as they land.

`web/e2e.mjs` drives the whole product through a real browser — create a
collection, upload a document, wait for the worker, ask a question, check the
citation resolves, ask a follow-up, reload, confirm an out-of-corpus question is
refused without citations, then delete:

```bash
node e2e.mjs          # needs the API, worker, and dev server running
```

### In LangGraph Studio

```bash
pip install "langgraph-cli[inmem]"
langgraph dev
```

Both graphs are registered in `langgraph.json` (`ingest` and `research_agent`),
so you can step through nodes, inspect state, and edit prompts live.

## Configuration

Everything tunable lives in dataclasses, surfaced to Studio and settable per-run
through `config["configurable"]` (or LangGraph 1.0 `context` — both are read).

| Field | Default | Notes |
| --- | --- | --- |
| `query_model` | `groq/openai/gpt-oss-20b` | Routing, planning, query generation — short, frequent, structured calls. |
| `response_model` | `groq/openai/gpt-oss-120b` | Writes the final cited answer. |
| `research_domain` | `the indexed research corpus` | What your corpus is about. Steers routing and answering. |
| `max_research_steps` | `3` | Steps per plan. Each is a full retrieval round — the main latency dial. |
| `queries_per_step` | `3` | Parallel searches per step. |
| `embedding_model` | `fastembed/BAAI/bge-small-en-v1.5` | Also `google/gemini-embedding-001`, `huggingface/…`, `openai/…`, `cohere/…`. |
| `retriever_provider` | `elastic-local` | Also `elastic` (Cloud), `pinecone`, `mongodb`. |
| `index_name` | `research_agent` | Use separate indexes for separate embedding models. |
| `collection_id` | `None` | Scopes indexing and retrieval to one corpus inside the index. |
| `search_kwargs` | `{"k": 5}` | Documents per query. |
| `chunk_size` / `chunk_overlap` | `1000` / `200` | Ingest only. |
| `arxiv_full_text` | `True` | Ingest only. Parse each paper's PDF; `False` indexes abstracts only. |

```python
config = {
    "configurable": {
        "research_domain": "clinical trial protocols",
        "index_name": "trials",
        "max_research_steps": 2,
    }
}
result = await graph.ainvoke({"messages": [{"role": "user", "content": "..."}]}, config)
```

Prompts are configuration too — override `router_system_prompt`,
`research_plan_system_prompt`, `response_system_prompt` and the rest without
touching `src/retrieval_graph/prompts.py`.

**Vector dimensions are fixed per index.** Changing `embedding_model` means
re-indexing into a fresh `index_name`, and querying with a different model than
you indexed with returns nonsense rather than an error.

## Swapping providers

Every backend is imported lazily, so the base install stays lean and you add only
what you use:

```bash
pip install -e ".[openai]"      # then embedding_model="openai/text-embedding-3-small"
pip install -e ".[pinecone]"    # then retriever_provider="pinecone"
pip install -e ".[anthropic]"   # then response_model="anthropic/claude-sonnet-5"
```

`load_chat_model` goes through `init_chat_model`, so changing LLM provider is a
config string and an install — no code change. Groq and Gemini are both base
dependencies, so `response_model="google_genai/gemini-3.5-flash"` works with only
a `GOOGLE_API_KEY` added.

## Tests

```bash
python -m pytest tests/unit_tests           # 107 tests, offline, no API key needed
python -m pytest tests/integration_tests    # needs docker compose up -d
```

The unit suite stubs the model and the retriever, so it exercises the real graph —
routing, planning, parallel research, de-duplication, plan truncation, abstention,
and citation resolution — without network access. The concurrency test blocks each
task until all of them have started, so it deadlocks rather than passes if the
steps ever go back to running one at a time. API tests run the real app against
SQLite and an in-memory queue, covering source lifecycle, job state transitions,
retry and recovery, SSE event order, and conversation persistence. Integration tests skip themselves cleanly when Elasticsearch is
down or `GROQ_API_KEY` is unset, and each uses a throwaway index it deletes
afterwards.

## Layout

```
web/                 Next.js frontend (App Router) + e2e.mjs browser test
src/
  shared/            configuration, retriever + embedding factories, reducers, citations
  ingest_graph/      loaders (files/arxiv/urls), chunking, indexing, pruning
  retrieval_graph/   router, planner, evidence gate, responder, prompts
    researcher_graph/  query expansion + parallel retrieval subgraph
  api/               FastAPI app, SQLAlchemy models, queue, worker
    routers/           collections, sources, threads
scripts/             ingest.py, ask.py -- CLI entrypoints
tests/               unit (offline) and integration (live infra)
```

## Notes and limits

- `docker-compose.yml` is a dev fixture: security is disabled and it binds to
  `127.0.0.1`. Not a production configuration.
- There is no authentication. Every collection is visible to every caller.
- Ingestion jobs run concurrently, but each job is internally sequential: an
  arXiv query downloads its papers' PDFs one after another.
- The frontend renders answers as plain text, so the model's markdown shows its
  own asterisks. Its self-written "Sources" section also repeats the resolved
  citation list below it.
- The schema is created with `create_all` on startup rather than migrations, so
  a schema change needs a fresh database.
- A research run makes several LLM calls, so a rate-limited key surfaces as a
  `429` in the answer step. `LLM_TIMEOUT_SECONDS` and `LLM_MAX_RETRIES` bound how
  long a throttled provider can stall a request.
- Retrieval is dense-only. No re-ranking, and no relevance grading of what comes
  back before it reaches the answer prompt.
- Structured calls use JSON-schema decoding rather than forced tool calls, and
  retry: Groq's gpt-oss models decline the tool call outright under
  `function_calling`, and return an empty generation for roughly one structured
  call in ten. `LLM_STRUCTURED_ATTEMPTS` tunes the retry budget.
- Citation numbers are resolved against the retrieved documents, so a marker
  pointing at nothing is caught. Markers are normalised to ASCII first, since
  some models emit CJK lenticular brackets. Nothing verifies that a correctly-resolved
  citation actually *supports* the sentence it is attached to.
- Collections share an index, and vector dimensions are fixed per index, so all
  collections in one index share an embedding model.
- `create_research_plan` clears documents from state, so each question starts
  from a clean evidence set — including follow-up questions in a `--chat`
  session, which re-retrieve rather than building on the previous turn.

Structure adapted from LangChain's
[rag-research-agent-template](https://github.com/langchain-ai/rag-research-agent-template).
