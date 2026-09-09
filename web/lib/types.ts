export type JobStatus = "pending" | "processing" | "completed" | "failed";
export type SourceKind = "files" | "arxiv" | "urls";

export interface Collection {
  id: string;
  slug: string;
  name: string;
  description: string;
  research_domain: string;
  index_name: string;
  embedding_model: string;
  created_at: string;
  source_count: number;
}

export interface Job {
  id: string;
  source_id: string;
  collection_id: string;
  status: JobStatus;
  stage: string;
  attempts: number;
  max_attempts: number;
  chunk_count: number;
  pruned_count: number;
  error: string;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
}

export interface Source {
  id: string;
  collection_id: string;
  kind: SourceKind;
  locator: string;
  title: string;
  status: JobStatus;
  chunk_count: number;
  error: string;
  created_at: string;
  updated_at: string;
  latest_job: Job | null;
}

export interface Citation {
  number: number;
  title: string;
  source: string;
  url: string;
  /** Opening of the cited passage. Absent on messages stored before snippets. */
  snippet?: string;
  resolved: boolean;
}

export interface Evidence {
  sufficient: boolean;
  reason: string;
  missing: string;
}

export interface Thread {
  id: string;
  collection_id: string;
  title: string;
  created_at: string;
}

export interface Message {
  id: string;
  thread_id: string;
  role: "user" | "assistant";
  content: string;
  plan: string[];
  citations: Citation[];
  evidence: Partial<Evidence>;
  created_at: string;
}

/** Events streamed by POST /threads/{id}/ask, in the order they arrive. */
export type ResearchEvent =
  | { type: "routed"; route: "research" | "more-info" | "general" }
  | { type: "plan"; steps: string[] }
  | { type: "step_complete"; step: string; document_count: number }
  | ({ type: "evidence" } & Evidence)
  | {
      type: "answer";
      content: string;
      citations: Citation[];
      plan: string[];
      evidence: Evidence;
    }
  | { type: "error"; message: string }
  | { type: "done" };
