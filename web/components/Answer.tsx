"use client";

import { Fragment, type ReactNode } from "react";

/**
 * Renders an answer as prose.
 *
 * The model writes Markdown and appends its own "Sources" list. The sources
 * section is dropped here because the Evidence cards above already show the
 * resolved citations, and showing both says the same thing twice.
 */
export function Answer({ text }: { text: string }) {
  const blocks = toBlocks(stripSourcesSection(text));
  return <div className="answer">{blocks}</div>;
}

const SOURCES_HEADING = /^\s*(?:#{1,6}\s*)?(?:\*\*)?sources(?:\*\*)?\s*:?\s*$/i;

export function stripSourcesSection(text: string): string {
  const lines = text.split("\n");
  for (let i = lines.length - 1; i >= 0; i--) {
    if (SOURCES_HEADING.test(lines[i])) {
      return lines.slice(0, i).join("\n").trimEnd();
    }
  }
  return text.trimEnd();
}

function toBlocks(text: string): ReactNode[] {
  const out: ReactNode[] = [];
  let list: { ordered: boolean; items: string[] } | null = null;

  const flush = () => {
    if (!list) return;
    const items = list.items.map((item, i) => <li key={i}>{inline(item)}</li>);
    out.push(
      list.ordered ? (
        <ol key={out.length}>{items}</ol>
      ) : (
        <ul key={out.length}>{items}</ul>
      ),
    );
    list = null;
  };

  for (const raw of text.split("\n")) {
    const line = raw.trimEnd();
    if (!line.trim()) {
      flush();
      continue;
    }

    const bullet = line.match(/^\s*[-*•]\s+(.*)$/);
    const numbered = line.match(/^\s*\d+[.)]\s+(.*)$/);
    const heading = line.match(/^#{1,6}\s+(.*)$/);

    if (bullet) {
      if (!list || list.ordered) flush();
      list ??= { ordered: false, items: [] };
      list.items.push(bullet[1]);
    } else if (numbered) {
      if (!list || !list.ordered) flush();
      list ??= { ordered: true, items: [] };
      list.items.push(numbered[1]);
    } else if (heading) {
      flush();
      out.push(
        <p key={out.length}>
          <strong>{inline(heading[1])}</strong>
        </p>,
      );
    } else {
      flush();
      out.push(<p key={out.length}>{inline(line)}</p>);
    }
  }
  flush();
  return out;
}

const INLINE = /(\*\*[^*]+\*\*|\*[^*\n]+\*|`[^`]+`|\[\d{1,3}\])/g;

function inline(text: string): ReactNode {
  return text.split(INLINE).map((part, i) => {
    if (!part) return null;
    if (/^\[\d{1,3}\]$/.test(part)) {
      return (
        <span className="cite" key={i}>
          {part}
        </span>
      );
    }
    if (part.startsWith("**") && part.endsWith("**")) {
      return <strong key={i}>{part.slice(2, -2)}</strong>;
    }
    if (part.startsWith("*") && part.endsWith("*") && part.length > 2) {
      return <em key={i}>{part.slice(1, -1)}</em>;
    }
    if (part.startsWith("`") && part.endsWith("`")) {
      return <code key={i}>{part.slice(1, -1)}</code>;
    }
    return <Fragment key={i}>{part}</Fragment>;
  });
}
