"use client";

import { use, useEffect, useState } from "react";

import { Chat } from "@/components/Chat";
import { api } from "@/lib/api";
import type { Collection } from "@/lib/types";

export default function ThreadPage({
  params,
}: {
  params: Promise<{ id: string; threadId: string }>;
}) {
  const { id, threadId } = use(params);
  const [collection, setCollection] = useState<Collection | null>(null);

  useEffect(() => {
    api
      .getCollection(id)
      .then(setCollection)
      .catch(() => setCollection(null));
  }, [id]);

  return (
    <main className="main">
      <div className="page-head">
        <span className="kicker">Research</span>
        <h1 className="title">{collection ? collection.name : "Thread"}</h1>
        {collection && <p className="lede">{collection.research_domain}</p>}
      </div>

      <Chat threadId={threadId} />
    </main>
  );
}
