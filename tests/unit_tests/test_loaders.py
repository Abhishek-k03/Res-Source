from ingest_graph.loaders import load_arxiv, load_local_files, load_urls


def test_loads_text_and_markdown_with_normalized_metadata(tmp_path):
    (tmp_path / "notes.md").write_text("# Heading\nbody", encoding="utf-8")
    (tmp_path / "plain.txt").write_text("some text", encoding="utf-8")

    docs = load_local_files(str(tmp_path))

    assert len(docs) == 2
    titles = {d.metadata["title"] for d in docs}
    assert titles == {"notes.md", "plain.txt"}
    assert all(d.metadata["source"] for d in docs)


def test_recurses_into_subdirectories(tmp_path):
    nested = tmp_path / "sub" / "deeper"
    nested.mkdir(parents=True)
    (nested / "a.txt").write_text("deep", encoding="utf-8")

    assert len(load_local_files(str(tmp_path))) == 1


def test_unsupported_extensions_are_skipped(tmp_path):
    (tmp_path / "data.parquet").write_bytes(b"\x00binary")
    (tmp_path / "keep.txt").write_text("keep", encoding="utf-8")

    docs = load_local_files(str(tmp_path))
    assert [d.metadata["title"] for d in docs] == ["keep.txt"]


def test_missing_directory_yields_nothing(tmp_path):
    assert load_local_files(str(tmp_path / "does-not-exist")) == []


def test_empty_inputs_short_circuit_without_network():
    assert load_arxiv("   ") == []
    assert load_urls([]) == []
