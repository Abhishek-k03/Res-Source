from langchain_core.documents import Document
from langchain_core.messages import AIMessage, HumanMessage

from shared.utils import format_docs, message_text


def test_message_text_reads_plain_string_content():
    assert message_text(AIMessage(content="hello")) == "hello"
    assert message_text(HumanMessage(content="a question")) == "a question"


def test_message_text_joins_content_blocks():
    # Gemini 3 returns text blocks rather than a bare string.
    message = AIMessage(
        content=[
            {"type": "text", "text": "first [1]. ", "extras": {"signature": "abc"}},
            {"type": "text", "text": "second [2]."},
        ]
    )
    assert message_text(message) == "first [1]. second [2]."


def test_message_text_skips_non_text_blocks():
    message = AIMessage(
        content=[
            {"type": "reasoning", "reasoning": "internal"},
            {"type": "text", "text": "visible"},
        ]
    )
    assert message_text(message) == "visible"


def test_message_text_of_empty_content_is_empty():
    assert message_text(AIMessage(content=[])) == ""


def test_empty_input_is_rendered_as_empty_documents():
    assert format_docs(None) == "<documents></documents>"
    assert format_docs([]) == "<documents></documents>"


def test_documents_are_numbered_for_citation():
    rendered = format_docs([Document(page_content="a"), Document(page_content="b")])
    assert 'index="1"' in rendered
    assert 'index="2"' in rendered


def test_citable_metadata_is_exposed_and_noise_is_dropped():
    doc = Document(
        page_content="body",
        metadata={"title": "Paper", "url": "http://x", "uuid": "abc", "junk": 1},
    )
    rendered = format_docs([doc])
    assert "Paper" in rendered and "http://x" in rendered
    assert "uuid" not in rendered and "junk" not in rendered


def test_content_is_preserved_verbatim():
    rendered = format_docs([Document(page_content="line one\nline two")])
    assert "line one\nline two" in rendered


def test_structured_output_falls_back_when_json_schema_is_unsupported():
    from shared.utils import structured_output

    class _Model:
        def __init__(self):
            self.calls = []

        def with_structured_output(self, schema, **kwargs):
            self.calls.append(kwargs.get("method"))
            if kwargs.get("method") == "json_schema":
                raise ValueError("unsupported method")
            return "bound"

    model = _Model()
    assert structured_output(model, dict) == "bound"
    assert model.calls == ["json_schema", None]
