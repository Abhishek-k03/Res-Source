from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from shared.state import UUID_KEY, drop_dedup_key, reduce_docs


def test_chunks_of_one_parent_do_not_collapse_into_a_single_document():
    # Regression: the splitter copies the parent's dedup key onto every chunk,
    # which collapsed a whole retrieval into one document.
    body = " ".join(f"word{i}" for i in range(2000))
    parent = reduce_docs(None, [Document(page_content=body)])
    assert UUID_KEY in parent[0].metadata

    splitter = RecursiveCharacterTextSplitter(chunk_size=200, chunk_overlap=0)
    chunks = drop_dedup_key(splitter.split_documents(parent))

    assert len(chunks) > 1
    assert all(UUID_KEY not in c.metadata for c in chunks)
    assert len(reduce_docs(None, chunks)) == len(chunks)


def test_drop_dedup_key_preserves_other_metadata_and_does_not_mutate_input():
    original = Document(page_content="x", metadata={UUID_KEY: "abc", "title": "T"})
    cleaned = drop_dedup_key([original])

    assert cleaned[0].metadata == {"title": "T"}
    assert original.metadata[UUID_KEY] == "abc"


def test_drop_dedup_key_is_a_no_op_without_the_key():
    docs = [Document(page_content="x", metadata={"title": "T"})]
    assert drop_dedup_key(docs)[0].metadata == {"title": "T"}


def test_appends_new_documents():
    existing = [Document(page_content="a", metadata={"uuid": "1"})]
    result = reduce_docs(existing, [Document(page_content="b")])
    assert [d.page_content for d in result] == ["a", "b"]


def test_drops_duplicate_content():
    # Parallel queries routinely retrieve the same chunk.
    first = reduce_docs(None, [Document(page_content="same")])
    second = reduce_docs(first, [Document(page_content="same")])
    assert len(second) == 1


def test_delete_clears_state():
    existing = [Document(page_content="a")]
    assert reduce_docs(existing, "delete") == []


def test_accepts_strings_and_dicts():
    from_string = reduce_docs(None, "hello")
    assert from_string[0].page_content == "hello"
    assert from_string[0].metadata["uuid"]

    from_dict = reduce_docs(None, [{"page_content": "x", "metadata": {"source": "s"}}])
    assert from_dict[0].metadata["source"] == "s"
    assert from_dict[0].metadata["uuid"]


def test_preserves_metadata_of_incoming_documents():
    result = reduce_docs(None, [Document(page_content="x", metadata={"title": "T"})])
    assert result[0].metadata["title"] == "T"
