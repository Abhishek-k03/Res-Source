"""Command-line entrypoint for the research agent.

Examples:
    python scripts/ask.py "How does query expansion help retrieval?"
    python scripts/ask.py --domain "retrieval-augmented generation research" --chat
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import uuid
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from langgraph.checkpoint.memory import MemorySaver

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from retrieval_graph.graph import builder  # noqa: E402
from shared.utils import message_text  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    """Define the CLI."""
    parser = argparse.ArgumentParser(description="Ask the research agent a question.")
    parser.add_argument("question", nargs="?", help="The question to research.")
    parser.add_argument(
        "--chat", action="store_true", help="Start an interactive session with memory."
    )
    parser.add_argument(
        "--index-name", default="research_agent", help="Vector index to search."
    )
    parser.add_argument(
        "--collection", default=None, help="Restrict the search to one collection."
    )
    parser.add_argument(
        "--embedding-model",
        default="fastembed/BAAI/bge-small-en-v1.5",
        help="Must match the model the index was built with.",
    )
    parser.add_argument(
        "--domain",
        default="the indexed research corpus",
        help="What your corpus is about; steers routing and answering.",
    )
    parser.add_argument("--query-model", default="groq/openai/gpt-oss-20b")
    parser.add_argument("--response-model", default="groq/openai/gpt-oss-120b")
    parser.add_argument(
        "--max-steps", type=int, default=3, help="Max steps in a research plan."
    )
    parser.add_argument(
        "--k", type=int, default=5, help="Documents retrieved per search query."
    )
    return parser


def report_progress(node: str, update: dict[str, Any]) -> None:
    """Print what each node did, so a long run is not a blank screen."""
    if node == "analyze_and_route_query":
        print(f"  routed as: {update['router']['type']}")
    elif node == "create_research_plan":
        for i, step in enumerate(update["steps"], start=1):
            print(f"  plan {i}. {step}")
    elif node == "conduct_research":
        for done in update["completed_steps"]:
            print(f"  researched: {done['step']} -> {done['document_count']} doc(s)")
    elif node == "assess_evidence":
        evidence = update["evidence"]
        if not evidence["sufficient"]:
            print(f"  insufficient evidence: {evidence['reason']}")


async def ask(graph: Any, config: dict[str, Any], question: str) -> None:
    """Stream one turn through the graph and print the final answer."""
    print(f"\n> {question}")
    final, citations = None, []
    async for chunk in graph.astream(
        {"messages": [{"role": "user", "content": question}]},
        config,
        stream_mode="updates",
    ):
        for node, update in chunk.items():
            report_progress(node, update)
            if "messages" in update:
                final = update["messages"][-1]
            citations = update.get("citations") or citations

    print("\n" + (message_text(final) if final else "(no response)"))
    unresolved = [c for c in citations if not c["resolved"]]
    if unresolved:
        numbers = ", ".join(f"[{c['number']}]" for c in unresolved)
        print(f"\nwarning: {numbers} cite no retrieved document.")


async def main() -> int:
    """Run a single question or an interactive chat session."""
    load_dotenv()
    args = build_parser().parse_args()
    if not args.question and not args.chat:
        build_parser().error("provide a question, or use --chat")

    # Checkpointer so a --chat session remembers earlier turns.
    graph = builder.compile(checkpointer=MemorySaver())
    config = {
        "configurable": {
            "thread_id": str(uuid.uuid4()),
            "index_name": args.index_name,
            "collection_id": args.collection,
            "embedding_model": args.embedding_model,
            "research_domain": args.domain,
            "query_model": args.query_model,
            "response_model": args.response_model,
            "max_research_steps": args.max_steps,
            "search_kwargs": {"k": args.k},
        }
    }

    if args.question:
        await ask(graph, config, args.question)
    if not args.chat:
        return 0

    print("\nInteractive session. Ctrl-C or an empty line to quit.")
    while True:
        try:
            question = input("\nyou> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if not question:
            return 0
        await ask(graph, config, question)


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
