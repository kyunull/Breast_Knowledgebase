from __future__ import annotations

from pathlib import Path

from app.citation import format_citation
from app.ingestion import make_node_metadata, read_jsonl


FIXTURES = Path(__file__).parent / "fixtures"


def test_pdf_zero_based_page_is_displayed_as_page_sequence() -> None:
    metadata = make_node_metadata(
        read_jsonl(FIXTURES / "nccn.jsonl")[0],
        guideline_id="nccn",
        version_id="nccn-v6",
        language="en",
        authority_level="primary_guideline",
        source_sha256="a" * 64,
        source_kind="pdf",
    )

    citation = format_citation(metadata)

    assert citation.locator == "PDF 页序号 1–2"
    assert citation.source_level == "primary_guideline"
    assert citation.raw_chunk_id == metadata["raw_chunk_id"]


def test_html_without_pages_uses_parent_heading_and_section_path() -> None:
    metadata = make_node_metadata(
        read_jsonl(FIXTURES / "oncotoolkit.jsonl")[0],
        guideline_id="oncotoolkit",
        version_id="oncotoolkit-2026",
        language="en",
        authority_level="secondary_summary",
        source_sha256="b" * 64,
        source_kind="html",
    )

    citation = format_citation(metadata)

    assert citation.locator == "HER2+ Breast Cancer > Metastatic disease"
    assert citation.source_level == "secondary_summary"
