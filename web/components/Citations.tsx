import type { Citation } from "@/lib/types";

/**
 * Citations resolved against the documents actually retrieved. An unresolved
 * one is shown rather than hidden: it means the model cited a document that
 * was not in its evidence.
 */
export function Citations({ citations }: { citations: Citation[] }) {
  if (citations.length === 0) return null;

  return (
    <div className="muted" style={{ marginTop: 8 }}>
      <strong>Sources</strong>
      <table>
        <tbody>
          {citations.map((c) => (
            <tr key={c.number}>
              <td style={{ width: 28 }}>[{c.number}]</td>
              <td>
                {c.resolved ? (
                  <>
                    {c.url ? (
                      <a href={c.url} target="_blank" rel="noreferrer">
                        {c.title}
                      </a>
                    ) : (
                      c.title
                    )}
                    {c.source && <span className="mono"> — {c.source}</span>}
                  </>
                ) : (
                  <span className="status-failed">
                    cites no retrieved document
                  </span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
