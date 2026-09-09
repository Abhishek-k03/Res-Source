from ingest_graph.configuration import IngestConfiguration
from retrieval_graph.configuration import AgentConfiguration
from shared.configuration import BaseConfiguration


def test_defaults_do_not_require_a_config():
    config = BaseConfiguration.from_runnable_config(None)
    assert config.retriever_provider == "elastic-local"
    assert config.embedding_model.startswith("fastembed/")
    assert config.index_name == "research_agent"


def test_configurable_values_override_defaults():
    config = AgentConfiguration.from_runnable_config(
        {"configurable": {"index_name": "papers", "max_research_steps": 1}}
    )
    assert config.index_name == "papers"
    assert config.max_research_steps == 1


def test_unknown_configurable_keys_are_ignored():
    # One config dict is shared by graphs with different config classes.
    config = IngestConfiguration.from_runnable_config(
        {"configurable": {"chunk_size": 42, "max_research_steps": 9, "thread_id": "x"}}
    )
    assert config.chunk_size == 42


def test_agent_config_inherits_shared_retrieval_fields():
    assert "index_name" in AgentConfiguration.__dataclass_fields__
    assert "embedding_model" in IngestConfiguration.__dataclass_fields__
