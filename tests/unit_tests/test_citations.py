from langchain_core.documents import Document

from shared.citations import cited_numbers, extract_citations

DOCS = [
    Document(
        page_content="a",
        metadata={"title": "Raft", "source": "raft.pdf", "url": "http://x/raft"},
    ),
    Document(page_content="b", metadata={"source": "notes.md"}),
]


def test_markers_are_deduplicated_and_ordered():
    assert cited_numbers("see [2] and [1], again [2]") == [1, 2]


def test_no_markers_means_no_citations():
    assert extract_citations("An answer with no references.", DOCS) == []


def test_a_marker_resolves_to_the_document_it_numbers():
    (citation,) = extract_citations("Leader election is described [1].", DOCS)

    assert citation["number"] == 1
    assert citation["title"] == "Raft"
    assert citation["source"] == "raft.pdf"
    assert citation["url"] == "http://x/raft"
    assert citation["resolved"] is True


def test_a_document_without_a_title_falls_back_to_its_source():
    (citation,) = extract_citations("As noted [2].", DOCS)
    assert citation["title"] == "notes.md"


def test_a_marker_past_the_evidence_is_reported_not_dropped():
    (citation,) = extract_citations("Invented reference [5].", DOCS)

    assert citation["number"] == 5
    assert citation["resolved"] is False


def test_citing_anything_without_evidence_is_unresolved():
    assert [c["resolved"] for c in extract_citations("Claim [1].", [])] == [False]
    assert [c["resolved"] for c in extract_citations("Claim [1].", None)] == [False]


def test_zero_is_not_a_valid_citation():
    # Documents are numbered from 1, so [0] points at nothing.
    (citation,) = extract_citations("Claim [0].", DOCS)
    assert citation["resolved"] is False


def test_cjk_lenticular_brackets_are_recognised_as_citations():
    # gpt-oss models emit U+3010/U+3011 rather than ASCII brackets.
    (citation,) = extract_citations("Leader election is described \u30101\u3011.", DOCS)
    assert citation["number"] == 1
    assert citation["resolved"] is True


def test_markers_are_normalised_to_ascii():
    from shared.citations import normalize_markers

    assert normalize_markers("a \u30101\u3011 and [2]") == "a [1] and [2]"
    assert normalize_markers("no markers here") == "no markers here"


def test_a_resolved_citation_carries_the_passage_it_came_from():
    docs = [
        Document(
            page_content="Slow-wave sleep loss impairs consolidation.",
            metadata={"title": "Walker"},
        )
    ]
    (citation,) = extract_citations("As shown [1].", docs)
    assert citation["snippet"] == "Slow-wave sleep loss impairs consolidation."


def test_a_long_passage_is_truncated_on_a_word_boundary():
    from shared.citations import SNIPPET_CHARS

    docs = [Document(page_content="word " * 200, metadata={"title": "Long"})]
    (citation,) = extract_citations("See [1].", docs)

    assert len(citation["snippet"]) <= SNIPPET_CHARS + 1
    assert citation["snippet"].endswith("\u2026")
    assert "  " not in citation["snippet"]


def test_an_unresolved_citation_has_no_snippet():
    (citation,) = extract_citations("Invented [9].", DOCS)
    assert citation["snippet"] == ""


def test_a_snippet_drops_a_leading_markdown_heading_marker():
    docs = [
        Document(page_content="## Safety\nRaft never overwrites entries.", metadata={})
    ]
    (citation,) = extract_citations("See [1].", docs)
    assert citation["snippet"] == "Safety Raft never overwrites entries."
