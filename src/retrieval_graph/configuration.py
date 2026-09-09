"""Configurable parameters for the retrieval graph."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Annotated

from retrieval_graph import prompts
from shared.configuration import BaseConfiguration


@dataclass(kw_only=True)
class AgentConfiguration(BaseConfiguration):
    """Models, prompts, and research budget for the retrieval agent."""

    query_model: Annotated[str, {"__template_metadata__": {"kind": "llm"}}] = field(
        default="groq/openai/gpt-oss-20b",
        metadata={
            "description": (
                "Model for routing, planning, and query generation -- the short, "
                "frequent, structured calls. Format: provider/model-name."
            )
        },
    )

    response_model: Annotated[str, {"__template_metadata__": {"kind": "llm"}}] = field(
        default="groq/openai/gpt-oss-120b",
        metadata={
            "description": (
                "Model that writes the final grounded answer. "
                "Format: provider/model-name."
            )
        },
    )

    research_domain: str = field(
        default="the indexed research corpus",
        metadata={
            "description": (
                "What your corpus is about, as a short noun phrase. Interpolated into "
                "every prompt, so it decides what counts as on-topic."
            )
        },
    )

    max_research_steps: int = field(
        default=3,
        metadata={
            "description": "Cap on research steps. Each one is a full retrieval round."
        },
    )

    queries_per_step: int = field(
        default=3,
        metadata={"description": "Parallel search queries per research step."},
    )

    router_system_prompt: str = field(
        default=prompts.ROUTER_SYSTEM_PROMPT,
        metadata={"description": "Classifies the user's question to route it."},
    )

    more_info_system_prompt: str = field(
        default=prompts.MORE_INFO_SYSTEM_PROMPT,
        metadata={"description": "Asks the user for the missing information."},
    )

    general_system_prompt: str = field(
        default=prompts.GENERAL_SYSTEM_PROMPT,
        metadata={"description": "Responds to off-topic or conversational messages."},
    )

    research_plan_system_prompt: str = field(
        default=prompts.RESEARCH_PLAN_SYSTEM_PROMPT,
        metadata={"description": "Turns the question into a short research plan."},
    )

    generate_queries_system_prompt: str = field(
        default=prompts.GENERATE_QUERIES_SYSTEM_PROMPT,
        metadata={"description": "Expands one step into several search queries."},
    )

    response_system_prompt: str = field(
        default=prompts.RESPONSE_SYSTEM_PROMPT,
        metadata={"description": "Writes the final answer with citations."},
    )

    evidence_assessment_system_prompt: str = field(
        default=prompts.EVIDENCE_ASSESSMENT_SYSTEM_PROMPT,
        metadata={"description": "Decides whether the evidence can support an answer."},
    )

    abstain_system_prompt: str = field(
        default=prompts.ABSTAIN_SYSTEM_PROMPT,
        metadata={"description": "Explains why the corpus cannot answer the question."},
    )
