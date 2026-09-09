"""Command-line entrypoint for the ingest graph.

Examples:
    python scripts/ingest.py files --dir data
    python scripts/ingest.py arxiv "retrieval augmented generation" --max 5
    python scripts/ingest.py urls https://example.com/a https://example.com/b
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from ingest_graph.graph import graph  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    """Define the CLI. Shared options live on each subparser, so they follow the source."""
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--index-name", default="research_agent", help="Vector index to write to."
    )
    common.add_argument(
        "--collection", default=None, help="Index into a named collection."
    )
    common.add_argument(
        "--embedding-model",
        default="fastembed/BAAI/bge-small-en-v1.5",
        help="Embedding model as provider/model. Must match what you query with.",
    )
    common.add_argument(
        "--chunk-size", type=int, default=1000, help="Target characters per chunk."
    )
    common.add_argument(
        "--chunk-overlap",
        type=int,
        default=200,
        help="Characters shared between chunks.",
    )

    parser = argparse.ArgumentParser(
        description="Index documents for the research agent.",
        epilog="Shared options go after the source, e.g. 'ingest.py files --index-name papers'.",
    )
    sub = parser.add_subparsers(dest="source", required=True)

    files = sub.add_parser(
        "files",
        parents=[common],
        help="Index PDFs, Markdown, text, and HTML from a folder.",
    )
    files.add_argument("--dir", default="data", help="Directory to scan recursively.")

    arxiv = sub.add_parser(
        "arxiv", parents=[common], help="Search arXiv and index the matching papers."
    )
    arxiv.add_argument("query", help="arXiv search query.")
    arxiv.add_argument(
        "--max", type=int, default=5, dest="max_results", help="Papers to fetch."
    )
    arxiv.add_argument(
        "--abstracts-only",
        action="store_true",
        help="Skip the PDF downloads and index only abstracts: much faster, much shallower.",
    )

    urls = sub.add_parser("urls", parents=[common], help="Fetch and index web pages.")
    urls.add_argument("urls", nargs="+", help="One or more URLs.")

    return parser


async def main() -> int:
    """Run one ingestion pass and report how many chunks were written."""
    load_dotenv()
    logging.basicConfig(
        level=logging.INFO, format="%(levelname)s %(name)s: %(message)s"
    )
    for noisy in ("elastic_transport", "httpx", "urllib3", "httpcore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    args = build_parser().parse_args()
    config = {
        "configurable": {
            "index_name": args.index_name,
            "collection_id": args.collection,
            "embedding_model": args.embedding_model,
            "chunk_size": args.chunk_size,
            "chunk_overlap": args.chunk_overlap,
            "docs_dir": getattr(args, "dir", "data"),
            "arxiv_max_results": getattr(args, "max_results", 5),
            "arxiv_full_text": not getattr(args, "abstracts_only", False),
        }
    }
    state = {
        "source": args.source,
        "query": getattr(args, "query", ""),
        "urls": getattr(args, "urls", []),
    }

    result = await graph.ainvoke(state, config)
    count = result["indexed_count"]
    if count:
        print(f"\nIndexed {count} chunk(s) into '{args.index_name}'.")
        return 0

    print("\nNothing was indexed. Check that the source has readable documents.")
    return 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
