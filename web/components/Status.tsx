import type { Job, JobStatus } from "@/lib/types";

export function Status({ status }: { status: JobStatus }) {
  return <span className={`status status-${status}`}>{status}</span>;
}

/**
 * A job's coarse progress. The worker reports a stage per ingest node, so a
 * long ingestion shows what it is doing rather than a bare spinner.
 */
export function JobProgress({ job }: { job: Job | null }) {
  if (!job) return null;

  if (job.status === "completed") {
    return (
      <span className="muted">
        {job.chunk_count} chunk{job.chunk_count === 1 ? "" : "s"} indexed
        {job.pruned_count > 0 && `, ${job.pruned_count} stale pruned`}
      </span>
    );
  }

  if (job.status === "failed") {
    return (
      <span className="muted">
        failed after {job.attempts}/{job.max_attempts} attempts
      </span>
    );
  }

  const stages = ["queued", "loading", "splitting", "indexing", "pruning"];
  const reached = stages.indexOf(job.stage);
  return (
    <span className="muted">
      {stages
        .map((stage, i) => (i <= reached ? stage : null))
        .filter(Boolean)
        .join(" → ")}
      {job.chunk_count > 0 && ` (${job.chunk_count} chunks)`}
    </span>
  );
}
