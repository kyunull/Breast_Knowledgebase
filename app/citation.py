from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


@dataclass(frozen=True, slots=True)
class Citation:
    source_title: str
    guideline_id: str
    version_id: str
    locator: str
    source_level: str
    source_ordinal: int
    raw_chunk_id: str


def format_citation(metadata: Mapping[str, object]) -> Citation:
    """Render an evidence locator without misrepresenting PDF page sequences."""
    source_kind = str(metadata["source_kind"])
    page_start = metadata.get("page_start")
    page_end = metadata.get("page_end")
    if source_kind == "pdf" and isinstance(page_start, int):
        start = page_start + 1
        end = page_end + 1 if isinstance(page_end, int) else start
        locator = f"PDF 页序号 {start}" if end == start else f"PDF 页序号 {start}–{end}"
    else:
        parent_h1 = metadata.get("parent_h1")
        section_path = metadata.get("section_path")
        parts = [str(value) for value in (parent_h1, section_path) if value]
        locator = " > ".join(parts) or "未提供定位信息"
    return Citation(
        source_title=str(metadata["doc_title"]),
        guideline_id=str(metadata["guideline_id"]),
        version_id=str(metadata["version_id"]),
        locator=locator,
        source_level=str(metadata["authority_level"]),
        source_ordinal=int(metadata["source_ordinal"]),
        raw_chunk_id=str(metadata["raw_chunk_id"]),
    )
