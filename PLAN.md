You are continuing development of an existing project called **Research RAG Agent**.

## Goal

Turn the existing project into a **useful, user-facing AI research assistant whose main engineering value is LangChain + LangGraph multi-step AI orchestration**.

This is NOT intended to become another generic RAG chatbot.

The project should demonstrate that I can design and implement a real AI workflow where multiple LLM-driven stages collaborate to research a question, while also having enough product engineering around it to make the system genuinely usable.

The core identity should be:

> **An AI research helper that takes a research question, creates a research plan, executes multiple research tasks in parallel, gathers evidence from a user's corpus, and produces a cited answer while abstaining when the available evidence is insufficient.**

---

# 1. IMPORTANT: Start by understanding the existing project

Before changing anything:

1. Inspect the entire repository.
2. Understand the current architecture and directory structure.
3. Read the existing LangGraph graphs, nodes, state definitions, configuration, ingestion pipeline, retrieval code, models, tests, CLIs, and Docker setup.
4. Run the existing test suite.
5. Identify what is already implemented versus what is missing.
6. Do NOT rewrite working components just to introduce a different architecture.
7. Preserve the existing good work, especially:
   - two graphs registered in `langgraph.json`
   - ingestion graph
   - research graph
   - researcher subgraph
   - parallel research execution
   - configurable models/prompts/research budget
   - normalized metadata
   - SHA-256 based idempotent ingestion
   - Elasticsearch integration
   - source types: local files, arXiv, web URLs
   - citation support
   - abstention behavior
   - existing tests

The current system has already addressed several bugs:

- LangGraph v1 API migration
- Gemini returning content blocks instead of plain strings
- arXiv 2.0 API changes
- incorrect retrieval deduplication
- non-idempotent ingestion

Do not regress these.

---

# 2. Product direction

The project should evolve from:

> "A technically interesting RAG agent with CLIs"

into:

> "A usable AI research application powered by a multi-agent/multi-step LangGraph workflow."

The agent architecture should remain the centerpiece.

Do NOT optimize the project primarily around retrieval benchmarks or ML metrics.

Scrybe is already my retrieval-focused project. Research RAG should be differentiated from it.

### Scrybe focuses on:

```text
crawl → chunk → hybrid retrieval → reranking → answer
```

### Research RAG should focus on:

```text
question
    ↓
triage
    ↓
research planning
    ↓
parallel research tasks
    ↓
evidence collection
    ↓
synthesis
    ↓
cited answer
```

Therefore, do not turn this project into another hybrid-search/reranking benchmark project unless there is a strong architectural reason.

---

# 3. Desired user experience

Build toward a simple web application.

The user should eventually be able to:

### A. Create/select a research collection

For example:

```text
Distributed Systems
Machine Learning
Operating Systems
My Research
```

Each collection represents an isolated corpus.

### B. Add sources

Support the existing source types:

- PDF
- Markdown
- text
- HTML
- web URL
- arXiv

The user should be able to see the status of ingestion.

For example:

```text
Raft.pdf

✓ Loaded
✓ Split
✓ Embedded
→ Indexing
```

### C. Ask a research question

Example:

> Compare Kafka and RabbitMQ for an order-processing system. Which should I use and why?

The system should expose the research process rather than appearing to be a single LLM call.

For example:

```text
Researching...

✓ Understanding question
✓ Created research plan

✓ Delivery guarantees
✓ Scalability
→ Operational complexity
→ Failure handling
○ Use cases
```

### D. Receive a cited answer

The final response should clearly distinguish:

- conclusion/recommendation
- reasoning
- evidence
- sources

Citations should point back to the actual retrieved source metadata.

---

# 4. Preserve and strengthen the LangGraph architecture

The current architecture is conceptually:

```text
User question
      ↓
   Triage
      ↓
 Research plan
      ↓
 Researcher subgraph
      ↓
 ┌────┼────┐
 ↓    ↓    ↓
R1   R2   R3
 ↓    ↓    ↓
 └────┼────┘
      ↓
 Evidence
      ↓
 Synthesis
      ↓
 Cited answer
```

Keep this architecture.

Where useful, make the graph boundaries explicit and clean.

The important concepts I want demonstrated are:

- typed state
- structured LLM outputs
- conditional routing
- subgraphs
- parallel execution
- state propagation
- configurable context
- research budgets
- failure handling
- evidence aggregation
- synthesis
- citations
- abstention

Avoid adding agents simply for the sake of saying "multi-agent".

Every node/subgraph should have a clear responsibility.

---

# 5. Product engineering to add

Prioritize the following features.

## Priority 1 — API + web interface

Create a clean separation:

```text
Next.js frontend
       ↓
FastAPI API
       ↓
LangGraph application
       ↓
Elasticsearch / PostgreSQL / Redis
```

The existing CLIs should continue working.

Do not make the web UI replace the underlying graph architecture.

---

## Priority 2 — Persistent research collections

Introduce a concept such as:

```text
Workspace / Collection
    ├── Sources
    ├── Ingestion jobs
    └── Research conversations
```

A retrieval operation must be scoped to the selected collection.

This should be implemented properly rather than merely filtering results in the frontend.

---

## Priority 3 — Persistent conversations

Allow a user to continue a research conversation.

Conceptually:

```text
Collection
    ↓
Thread
    ↓
Messages
```

The system should preserve enough state to support follow-up questions.

For example:

```text
User:
Compare Kafka and RabbitMQ.

Assistant:
...

User:
Now compare their failure recovery.

Assistant:
...
```

Use PostgreSQL if appropriate.

Do not unnecessarily introduce another database.

---

## Priority 4 — Asynchronous ingestion

Do not make a large ingestion request block the API request.

Use the existing Redis infrastructure if appropriate:

```text
POST /sources
      ↓
create ingestion job
      ↓
queue
      ↓
worker
      ↓
ingestion graph
      ↓
Elasticsearch
```

Expose job status through the API.

Support:

- pending
- processing
- completed
- failed

Include retry behavior where appropriate.

The goal is to demonstrate real backend engineering, not merely upload a file and synchronously process it.

---

## Priority 5 — Source lifecycle

Fix the currently known problem where edited documents can leave stale chunks.

Sources should have stable identities and versions/content hashes.

Support:

- add source
- delete source
- re-index source
- update changed source
- prevent duplicate ingestion

Do not break the existing idempotency guarantees.

---

## Priority 6 — Streaming/progress

Where practical, stream research progress to the frontend.

The user should be able to see something like:

```text
Triage complete
Research plan created
Running 3 research tasks
Retrieved 12 relevant passages
Synthesizing answer
```

Do not expose raw internal chain-of-thought.

Expose only safe high-level workflow status and useful metadata.

---

# 6. Retrieval philosophy

Do NOT make retrieval sophistication the main project goal.

The current dense retrieval implementation is acceptable as a baseline.

A small amount of retrieval improvement is fine if required for correctness, but avoid turning this into:

```text
BM25 vs dense vs hybrid vs reranker
```

That is the focus of Scrybe.

For Research RAG, retrieval exists to provide evidence to the research workflow.

The interesting question is:

> How do multiple research tasks use retrieved evidence to produce a useful answer?

not:

> Can I increase recall@5 by another 10%?

---

# 7. Configuration

Preserve the existing configuration philosophy.

Models, prompts, research budgets, embedding providers, and corpus settings should remain configurable rather than hardcoded.

Continue supporting the existing Gemini setup and provider abstraction where already implemented.

Do not introduce unnecessary provider complexity.

---

# 8. Testing

Maintain the existing test suite.

Add tests for newly introduced behavior, especially:

- workspace/collection isolation
- source lifecycle
- ingestion job state transitions
- idempotent re-ingestion
- deleted/updated source behavior
- research graph routing
- parallel research execution
- insufficient-evidence abstention
- citation propagation
- API behavior

Prefer deterministic/offline tests by mocking/stubbing LLM and retrieval dependencies.

Keep live integration tests separate.

Do not make the entire test suite dependent on API keys.

---

# 9. Do not overengineer

This is a resume project, not a production SaaS company.

Avoid unnecessary additions such as:

- microservices everywhere
- Kubernetes unless genuinely useful
- complicated authentication systems
- elaborate billing
- unnecessary vector databases
- multiple queues
- excessive agent hierarchies
- artificial benchmarks

Favor a clean architecture that I can explain in an interview.

---

# 10. Definition of success

The finished project should allow me to demonstrate:

### AI engineering

- LangChain
- LangGraph
- structured LLM workflows
- subgraphs
- parallel execution
- RAG
- evidence-grounded synthesis
- citations
- abstention

### Backend engineering

- FastAPI
- PostgreSQL
- Redis
- Elasticsearch
- background jobs
- asynchronous processing
- idempotency
- source lifecycle
- API design

### Frontend engineering

- Next.js
- research/chat interface
- source management
- progress/streaming
- citations

The result should feel like a real application rather than a collection of notebooks or agent demos.

---

# 11. Development process

Work incrementally.

First produce a concise assessment:

1. Current architecture
2. What already works
3. What is missing for the desired product
4. Recommended implementation order
5. Any architectural risks

Then implement the highest-value pieces.

Do not ask for approval for every small implementation detail.

However, if you discover a major architectural decision that would substantially change the existing system, stop and explain the tradeoff before making that change.

After each meaningful phase:

1. Run relevant tests.
2. Fix regressions.
3. Check that existing CLIs still work.
4. Keep the code clean and typed.
5. Update documentation where appropriate.

At the end, provide:

- what was implemented
- architecture changes
- tests added/passed
- remaining limitations
- how to run the application locally

---

# 12. Most important constraint

Do not lose sight of the project's core identity:

> **This is a LangGraph/LangChain-powered AI research orchestration system.**

The frontend, persistence, ingestion jobs, and other engineering features exist to make that orchestration **useful to a real user**.

Do not reduce the project to a normal RAG chatbot.

Do not optimize it solely for benchmark metrics.

Make the agent workflow the reason the application exists.
