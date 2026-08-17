from __future__ import annotations

import argparse
from dataclasses import dataclass
from html import escape
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
from tempfile import NamedTemporaryFile
from typing import Any, Mapping, Sequence


DOC_ID = "csco_breast_2026"
DOC_TITLE = "2026 CSCO乳腺癌诊疗指南"
_PAGE_HEADING_RE = re.compile(r"(?m)^## PDF page (?P<page>\d+)\s*$")
_MARKDOWN_HEADING_RE = re.compile(r"(?m)^(?P<hashes>#{1,6})\s+(?P<text>.+?)\s*$")
_CENTERED_TEXT_RE = re.compile(
    r'<div\b[^>]*style="[^"]*text-align:\s*center[^\"]*"[^>]*>'
    r"(?P<text>(?:(?!<img\b).)*?)</div>",
    re.IGNORECASE | re.DOTALL,
)
_TABLE_IMAGE_RE = re.compile(
    r'<div\b[^>]*>\s*<img\b[^>]*\bsrc="(?P<src>[^\"]*'
    r"img_in_table_box_(?P<left>\d+)_(?P<top>\d+)_(?P<right>\d+)_(?P<bottom>\d+)\.jpg)"
    r"[^>]*>\s*</div>",
    re.IGNORECASE | re.DOTALL,
)
_IMAGE_BLOCK_RE = re.compile(
    r"<div\b[^>]*>\s*<img\b[^>]*>\s*</div>", re.IGNORECASE | re.DOTALL
)
_MAX_TEXT_CHARS = 900


@dataclass(frozen=True, slots=True)
class ConversionReport:
    markdown_replacements: int
    table_count: int
    row_record_count: int
    text_record_count: int
    page_count: int


@dataclass(frozen=True, slots=True)
class _Cell:
    row_tl: int
    col_tl: int
    row_br: int
    col_br: int
    text: str
    confidence: float | None


@dataclass(frozen=True, slots=True)
class _TableGrid:
    cells: tuple[_Cell, ...]
    rows: int
    columns: int
    occupancy: tuple[tuple[_Cell | None, ...], ...]


class _HtmlTextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        if tag.lower() == "br":
            self.parts.append("\n")

    def handle_startendtag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        self.handle_starttag(tag, attrs)


def render_table_html(table: Mapping[str, object]) -> str:
    """Render one Tencent table with its original cell spans preserved."""
    grid = _build_grid(table)
    lines = [
        '<table class="ocr-table" style="border-collapse: collapse; width: 83%; margin: 0 auto; table-layout: fixed;">'
    ]
    origins = {(cell.row_tl, cell.col_tl): cell for cell in grid.cells}
    for row_index in range(grid.rows):
        lines.append("  <tr>")
        for column_index in range(grid.columns):
            cell = grid.occupancy[row_index][column_index]
            if cell is not None and (cell.row_tl, cell.col_tl) != (row_index, column_index):
                continue
            if cell is None:
                lines.append(_render_empty_html_cell())
                continue
            if origins[(row_index, column_index)] != cell:
                raise ValueError("table cell origin is inconsistent")
            tag = "th" if row_index == 0 else "td"
            spans = _html_span_attributes(cell)
            rendered = escape(cell.text, quote=False).replace("\n", "<br>") or "&nbsp;"
            lines.append(
                f'    <{tag}{spans} style="border: 1px solid #444; padding: 5px; '
                f'white-space: pre-wrap; overflow-wrap: anywhere; vertical-align: top;">{rendered}</{tag}>'
            )
        lines.append("  </tr>")
    lines.append("</table>")
    return "\n".join(lines)


def linearize_table_rows(table: Mapping[str, object], *, table_title: str) -> list[str]:
    """Create header-qualified text records without splitting any physical table row."""
    grid = _build_grid(table)
    header_segments = _header_segments(grid)
    header_line = "；".join(
        f"{segment}={_inline_text(cell.text)}" for segment, cell in header_segments
    )
    rows = [f"表格：{table_title}\n表头：{header_line}"]
    column_labels = _column_labels(grid)
    for row_index in range(1, grid.rows):
        values = []
        for column_index, label in enumerate(column_labels):
            cell = grid.occupancy[row_index][column_index]
            value = "" if cell is None else _inline_text(cell.text)
            values.append(f"{label}={value}")
        rows.append(f"表格：{table_title}\n第{row_index + 1}行：" + "；".join(values))
    return rows


def convert_csco_ocr(
    *,
    source_markdown: Path,
    tencent_json_dir: Path,
    output_markdown: Path,
    output_jsonl: Path,
) -> ConversionReport:
    """Restore all table images in a CSCO OCR source and emit retrieval records."""
    source_path = Path(source_markdown).resolve()
    output_markdown_path = Path(output_markdown).resolve()
    output_jsonl_path = Path(output_jsonl).resolve()
    tencent_path = Path(tencent_json_dir).resolve()
    if source_path == output_markdown_path:
        raise ValueError("output_markdown must not overwrite source_markdown")
    if not source_path.is_file():
        raise FileNotFoundError(source_path)
    if not tencent_path.is_dir():
        raise NotADirectoryError(tencent_path)

    source = source_path.read_text(encoding="utf-8")
    page_matches = list(_PAGE_HEADING_RE.finditer(source))
    if not page_matches:
        raise ValueError("source Markdown does not contain PDF page markers")

    heading_stack: list[str] = []
    prefix = source[: page_matches[0].start()]
    output_parts = [prefix]
    all_records: list[dict[str, object]] = []
    replacements = 0
    table_count = 0
    row_record_count = 0
    text_record_count = 0
    image_pages: set[int] = set()

    for page_index, page_match in enumerate(page_matches):
        page = int(page_match.group("page"))
        section_end = (
            page_matches[page_index + 1].start()
            if page_index + 1 < len(page_matches)
            else len(source)
        )
        section = source[page_match.start() : section_end]
        rendered_section, records, matched_images = _convert_page_section(
            section=section,
            page=page,
            heading_stack=heading_stack,
            tencent_json_dir=tencent_path,
        )
        output_parts.append(rendered_section)
        all_records.extend(records)
        replacements += matched_images
        table_count += sum(record["block_type"] == "table" for record in records)
        row_record_count += sum(record["block_type"] == "table_row" for record in records)
        text_record_count += sum(record["block_type"] in {"paragraph", "note"} for record in records)
        if matched_images:
            image_pages.add(page)

    _reject_unreferenced_valid_tables(tencent_path, image_pages)
    restored = "".join(output_parts)
    if _TABLE_IMAGE_RE.search(restored):
        raise RuntimeError("not every table image was replaced")
    _validate_records(all_records)
    _write_text_atomic(output_markdown_path, restored)
    jsonl = "".join(
        json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n"
        for record in all_records
    )
    _write_text_atomic(output_jsonl_path, jsonl)
    return ConversionReport(
        markdown_replacements=replacements,
        table_count=table_count,
        row_record_count=row_record_count,
        text_record_count=text_record_count,
        page_count=len(image_pages),
    )


def _convert_page_section(
    *,
    section: str,
    page: int,
    heading_stack: list[str],
    tencent_json_dir: Path,
) -> tuple[str, list[dict[str, object]], int]:
    matches = list(_TABLE_IMAGE_RE.finditer(section))
    if not matches:
        records, _ = _make_text_records(
            section,
            page=page,
            heading_stack=heading_stack,
            start_block_index=1,
        )
        return section, records, 0

    payload_path = tencent_json_dir / f"source-page-{page:03d}.json"
    if not payload_path.is_file():
        raise FileNotFoundError(f"missing Tencent table OCR response for PDF page {page}: {payload_path}")
    payload = _read_json_object(payload_path)
    tables = _valid_tables(payload)
    table_groups = _group_tables_by_image(matches, tables, page=page)

    parts: list[str] = []
    records: list[dict[str, object]] = []
    cursor = 0
    next_block_index = 1
    for image_match in matches:
        before_image = section[cursor : image_match.start()]
        text_records, next_block_index = _make_text_records(
            before_image,
            page=page,
            heading_stack=heading_stack,
            start_block_index=next_block_index,
        )
        records.extend(text_records)
        parts.append(before_image)
        rendered_tables: list[str] = []
        for table_index, table in table_groups[image_match.start()]:
            table_id = f"csco_2026_p{page:03d}_t{table_index:02d}"
            title = _table_title(before_image, heading_stack, page, table_index)
            source_image = image_match.group("src")
            rendered_tables.append(
                _render_table_block(
                    table=table,
                    page=page,
                    table_index=table_index,
                    table_id=table_id,
                    table_title=title,
                )
            )
            records.extend(
                _make_records(
                    table=table,
                    page=page,
                    table_id=table_id,
                    table_index=table_index,
                    table_title=title,
                    section_path=_section_path(heading_stack, page),
                    source_image=source_image,
                )
            )
        parts.append("\n\n".join(rendered_tables))
        cursor = image_match.end()
    trailing = section[cursor:]
    text_records, _ = _make_text_records(
        trailing,
        page=page,
        heading_stack=heading_stack,
        start_block_index=next_block_index,
    )
    records.extend(text_records)
    parts.append(trailing)
    return "".join(parts), records, len(matches)


def _make_text_records(
    text: str,
    *,
    page: int,
    heading_stack: list[str],
    start_block_index: int,
) -> tuple[list[dict[str, object]], int]:
    records: list[dict[str, object]] = []
    pending: list[str] = []
    pending_section = ""
    pending_type = "paragraph"
    next_block_index = start_block_index

    def flush() -> None:
        nonlocal next_block_index, pending, pending_section, pending_type
        if not pending:
            return
        record: dict[str, object] = {
            "chunk_id": f"csco_2026_p{page:03d}_b{next_block_index:03d}",
            "doc_id": DOC_ID,
            "doc_title": DOC_TITLE,
            "section_path": pending_section,
            "page_code": f"PDF-{page:03d}",
            "page_start": page - 1,
            "page_end": page - 1,
            "block_type": pending_type,
            "text": "\n\n".join(pending),
        }
        if heading_stack:
            record["parent_h1"] = heading_stack[0]
            record["heading_level"] = len(heading_stack)
        records.append(record)
        next_block_index += 1
        pending = []
        pending_section = ""
        pending_type = "paragraph"

    def append_paragraph(value: str) -> None:
        nonlocal pending_section, pending_type
        normalized = _normalize_text_block(value)
        if not normalized:
            return
        section = _section_path(heading_stack, page)
        block_type = "note" if normalized.startswith(("注：", "注:")) else "paragraph"
        for piece in _split_long_text(normalized):
            combined_length = sum(len(item) for item in pending) + len(piece) + 2 * len(pending)
            if pending and (
                pending_section != section
                or pending_type != block_type
                or combined_length > _MAX_TEXT_CHARS
            ):
                flush()
            if not pending:
                pending_section = section
                pending_type = block_type
            pending.append(piece)

    for raw_block in re.split(r"\n[ \t]*\n+", text):
        content_lines: list[str] = []
        for line in raw_block.splitlines():
            heading_match = _MARKDOWN_HEADING_RE.fullmatch(line.strip())
            if heading_match is None:
                content_lines.append(line)
                continue
            append_paragraph("\n".join(content_lines))
            content_lines = []
            flush()
            _apply_heading_match(heading_match, heading_stack)
        append_paragraph("\n".join(content_lines))
    flush()
    return records, next_block_index


def _normalize_text_block(value: str) -> str:
    without_images = _IMAGE_BLOCK_RE.sub("", value)
    decoded = _html_to_text(without_images).replace("\r\n", "\n").replace("\r", "\n")
    lines = [
        line.rstrip()
        for line in decoded.splitlines()
        if not re.fullmatch(r"\s*---+\s*", line)
    ]
    return "\n".join(lines).strip()


def _split_long_text(value: str) -> list[str]:
    pieces: list[str] = []
    remaining = value
    while len(remaining) > _MAX_TEXT_CHARS:
        window = remaining[:_MAX_TEXT_CHARS]
        sentence_ends = [
            match.end() for match in re.finditer(r"[。！？；\n]", window)
        ]
        cut = sentence_ends[-1] if sentence_ends else _MAX_TEXT_CHARS
        pieces.append(remaining[:cut])
        remaining = remaining[cut:]
    if remaining:
        pieces.append(remaining)
    return pieces


def _group_tables_by_image(
    images: Sequence[re.Match[str]],
    tables: Sequence[Mapping[str, object]],
    *,
    page: int,
) -> dict[int, list[tuple[int, Mapping[str, object]]]]:
    sorted_images = sorted(images, key=lambda image: int(image.group("top")))
    sorted_tables = sorted(tables, key=_table_top)
    groups: dict[int, list[tuple[int, Mapping[str, object]]]] = {
        image.start(): [] for image in sorted_images
    }
    for table_index, table in enumerate(sorted_tables, start=1):
        table_top, table_bottom = _table_vertical_bounds(table)
        table_height = table_bottom - table_top
        candidates: list[tuple[float, re.Match[str]]] = []
        for image in sorted_images:
            image_top = int(image.group("top"))
            image_bottom = int(image.group("bottom"))
            image_height = image_bottom - image_top
            if image_height <= 0:
                raise ValueError(f"PDF page {page}: table image has invalid vertical bounds")
            overlap = max(0, min(table_bottom, image_bottom) - max(table_top, image_top))
            smaller_height = min(table_height, image_height)
            candidates.append((overlap / smaller_height, image))
        overlap_ratio, selected_image = max(candidates, key=lambda candidate: candidate[0])
        if overlap_ratio < 0.8:
            raise ValueError(
                f"PDF page {page}: Tencent table {table_index} does not substantially overlap "
                "any table image"
            )
        groups[selected_image.start()].append((table_index, table))
    if any(not group for group in groups.values()):
        raise ValueError(
            f"PDF page {page}: {len(sorted_images)} table images but "
            f"{len(sorted_tables)} valid Tencent tables"
        )
    return groups


def _make_records(
    *,
    table: Mapping[str, object],
    page: int,
    table_id: str,
    table_index: int,
    table_title: str,
    section_path: str,
    source_image: str,
) -> list[dict[str, object]]:
    grid = _build_grid(table)
    row_texts = linearize_table_rows(table, table_title=table_title)
    confidence_values = [cell.confidence for cell in grid.cells if cell.confidence is not None]
    metadata: dict[str, object] = {
        "table_id": table_id,
        "table_index": table_index,
        "table_title": table_title,
        "table_row_count": grid.rows,
        "table_column_count": grid.columns,
        "table_cell_count": len(grid.cells),
        "source_image": source_image,
        "ocr_confidence_min": min(confidence_values) if confidence_values else None,
        "ocr_confidence_mean": (
            round(sum(confidence_values) / len(confidence_values), 2)
            if confidence_values
            else None
        ),
    }
    common = {
        "doc_id": DOC_ID,
        "doc_title": DOC_TITLE,
        "section_path": section_path,
        "page_code": f"PDF-{page:03d}",
        "page_start": page - 1,
        "page_end": page - 1,
    }
    records: list[dict[str, object]] = [
        {
            "chunk_id": table_id,
            **common,
            "block_type": "table",
            "text": "\n\n".join(row_texts),
            **metadata,
        }
    ]
    for row_index, row_text in enumerate(row_texts, start=1):
        records.append(
            {
                "chunk_id": f"{table_id}_r{row_index:02d}",
                **common,
                "block_type": "table_row",
                "text": row_text,
                **metadata,
                "table_row_index": row_index,
                "parent_table_chunk_id": table_id,
            }
        )
    return records


def _render_table_block(
    *,
    table: Mapping[str, object],
    page: int,
    table_index: int,
    table_id: str,
    table_title: str,
) -> str:
    escaped_title = escape(table_title, quote=True)
    return (
        f'<div class="ocr-table-container" data-source-page="{page}" '
        f'data-table-index="{table_index}" data-table-id="{table_id}" '
        f'data-table-title="{escaped_title}" style="overflow-x: auto; margin: 1em 0;">\n'
        f"{render_table_html(table)}\n"
        "</div>"
    )


def _build_grid(table: Mapping[str, object]) -> _TableGrid:
    raw_cells = table.get("Cells")
    if not isinstance(raw_cells, list) or not raw_cells:
        raise ValueError("table must contain at least one cell")
    cells = tuple(_parse_cell(raw_cell) for raw_cell in raw_cells)
    rows = max(cell.row_br for cell in cells)
    columns = max(cell.col_br for cell in cells)
    occupancy: list[list[_Cell | None]] = [
        [None for _ in range(columns)] for _ in range(rows)
    ]
    for cell in cells:
        for row_index in range(cell.row_tl, cell.row_br):
            for column_index in range(cell.col_tl, cell.col_br):
                if occupancy[row_index][column_index] is not None:
                    raise ValueError(
                        f"table cells overlap at row {row_index + 1}, column {column_index + 1}"
                    )
                occupancy[row_index][column_index] = cell
    return _TableGrid(
        cells=cells,
        rows=rows,
        columns=columns,
        occupancy=tuple(tuple(row) for row in occupancy),
    )


def _parse_cell(raw_cell: object) -> _Cell:
    if not isinstance(raw_cell, Mapping):
        raise ValueError("table cell must be an object")
    values: dict[str, int] = {}
    for key in ("RowTl", "ColTl", "RowBr", "ColBr"):
        value = raw_cell.get(key)
        if not isinstance(value, int) or isinstance(value, bool):
            raise ValueError(f"table cell {key} must be an integer")
        values[key] = value
    if values["RowTl"] < 0 or values["ColTl"] < 0:
        raise ValueError("table cell coordinates must be non-negative")
    if values["RowBr"] <= values["RowTl"] or values["ColBr"] <= values["ColTl"]:
        raise ValueError("table cell spans must be positive")
    text = raw_cell.get("Text", "")
    if not isinstance(text, str):
        raise ValueError("table cell Text must be a string")
    confidence_raw = raw_cell.get("Confidence")
    confidence = (
        float(confidence_raw)
        if isinstance(confidence_raw, (int, float)) and not isinstance(confidence_raw, bool)
        else None
    )
    return _Cell(
        row_tl=values["RowTl"],
        col_tl=values["ColTl"],
        row_br=values["RowBr"],
        col_br=values["ColBr"],
        text=text.replace("\r\n", "\n").replace("\r", "\n").strip(),
        confidence=confidence,
    )


def _header_segments(grid: _TableGrid) -> list[tuple[str, _Cell]]:
    segments: list[tuple[str, _Cell]] = []
    column_index = 0
    while column_index < grid.columns:
        cell = grid.occupancy[0][column_index]
        if cell is None:
            segments.append((f"第{column_index + 1}列", _Cell(0, column_index, 1, column_index + 1, "", None)))
            column_index += 1
            continue
        if cell.row_tl == 0 and cell.col_tl == column_index:
            start = cell.col_tl + 1
            end = cell.col_br
            label = f"第{start}列" if start == end else f"第{start}-{end}列"
            segments.append((label, cell))
            column_index = cell.col_br
            continue
        label = f"第{column_index + 1}列"
        segments.append((label, cell))
        column_index += 1
    return segments


def _column_labels(grid: _TableGrid) -> list[str]:
    raw_labels = [
        _inline_text(cell.text) if cell is not None and cell.text else f"第{index + 1}列"
        for index, cell in enumerate(grid.occupancy[0])
    ]
    label_counts = {label: raw_labels.count(label) for label in raw_labels}
    return [
        f"{label}（第{index + 1}列）" if label_counts[label] > 1 else label
        for index, label in enumerate(raw_labels)
    ]


def _html_span_attributes(cell: _Cell) -> str:
    attributes: list[str] = []
    if cell.row_br - cell.row_tl > 1:
        attributes.append(f'rowspan="{cell.row_br - cell.row_tl}"')
    if cell.col_br - cell.col_tl > 1:
        attributes.append(f'colspan="{cell.col_br - cell.col_tl}"')
    return "" if not attributes else " " + " ".join(attributes)


def _render_empty_html_cell() -> str:
    return (
        '    <td style="border: 1px solid #444; padding: 5px; white-space: pre-wrap; '
        'overflow-wrap: anywhere; vertical-align: top;">&nbsp;</td>'
    )


def _inline_text(value: str) -> str:
    return value.replace("\r\n", "\n").replace("\r", "\n").strip()


def _valid_tables(payload: Mapping[str, object]) -> list[Mapping[str, object]]:
    detections = payload.get("TableDetections")
    if not isinstance(detections, list):
        raise ValueError("Tencent response does not contain a TableDetections list")
    tables = [
        detection
        for detection in detections
        if isinstance(detection, Mapping) and detection.get("Type") in {1, 2}
    ]
    for table in tables:
        _build_grid(table)
        _table_top(table)
    return tables


def _table_top(table: Mapping[str, object]) -> int:
    return _table_vertical_bounds(table)[0]


def _table_vertical_bounds(table: Mapping[str, object]) -> tuple[int, int]:
    points = table.get("TableCoordPoint")
    if not isinstance(points, list) or not points:
        raise ValueError("table is missing TableCoordPoint")
    values = []
    for point in points:
        if not isinstance(point, Mapping) or not isinstance(point.get("Y"), int):
            raise ValueError("table coordinate Y must be an integer")
        values.append(point["Y"])
    top = min(values)
    bottom = max(values)
    if bottom <= top:
        raise ValueError("table vertical bounds must have positive height")
    return top, bottom


def _read_json_object(path: Path) -> Mapping[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ValueError(f"invalid Tencent JSON: {path}: {error.msg}") from error
    if not isinstance(payload, Mapping):
        raise ValueError(f"Tencent JSON must be an object: {path}")
    return payload


def _update_heading_stack(text: str, heading_stack: list[str]) -> None:
    for match in _MARKDOWN_HEADING_RE.finditer(text):
        _apply_heading_match(match, heading_stack)


def _apply_heading_match(match: re.Match[str], heading_stack: list[str]) -> None:
    title = _clean_title(match.group("text"))
    if not title or title.startswith("PDF page "):
        return
    level = len(match.group("hashes"))
    del heading_stack[level - 1 :]
    heading_stack.append(title)


def _table_title(before_image: str, heading_stack: Sequence[str], page: int, table_index: int) -> str:
    candidates: list[tuple[int, str]] = []
    for match in _MARKDOWN_HEADING_RE.finditer(before_image):
        title = _clean_title(match.group("text"))
        if title and not title.startswith("PDF page "):
            candidates.append((match.start(), title))
    for match in _CENTERED_TEXT_RE.finditer(before_image):
        title = _clean_title(_strip_html(match.group("text")))
        if title:
            candidates.append((match.start(), title))
    if candidates:
        return max(candidates, key=lambda candidate: candidate[0])[1]
    if heading_stack:
        return heading_stack[-1]
    return f"PDF第{page}页表格{table_index}"


def _section_path(heading_stack: Sequence[str], page: int) -> str:
    return " > ".join(heading_stack) if heading_stack else f"PDF第{page}页"


def _clean_title(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _strip_html(value: str) -> str:
    return _html_to_text(value)


def _html_to_text(value: str) -> str:
    parser = _HtmlTextExtractor()
    parser.feed(value)
    parser.close()
    return "".join(parser.parts)


def _reject_unreferenced_valid_tables(tencent_json_dir: Path, image_pages: set[int]) -> None:
    for payload_path in sorted(tencent_json_dir.glob("source-page-*.json")):
        match = re.fullmatch(r"source-page-(\d{3})\.json", payload_path.name)
        if match is None:
            continue
        page = int(match.group(1))
        if page in image_pages:
            continue
        if _valid_tables(_read_json_object(payload_path)):
            raise ValueError(
                f"PDF page {page}: Tencent response contains valid tables but source Markdown has no table image"
            )


def _validate_records(records: Sequence[Mapping[str, object]]) -> None:
    required = {
        "chunk_id",
        "doc_id",
        "doc_title",
        "section_path",
        "page_code",
        "page_start",
        "page_end",
        "block_type",
        "text",
    }
    seen_ids: set[str] = set()
    for record in records:
        missing = required - set(record)
        if missing:
            raise ValueError(f"record is missing fields: {sorted(missing)}")
        chunk_id = record["chunk_id"]
        text = record["text"]
        if not isinstance(chunk_id, str) or not chunk_id:
            raise ValueError("record chunk_id must be a non-empty string")
        if chunk_id in seen_ids:
            raise ValueError(f"duplicate chunk_id: {chunk_id}")
        if not isinstance(text, str) or not text:
            raise ValueError(f"record {chunk_id} has empty text")
        seen_ids.add(chunk_id)


def _write_text_atomic(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(
        mode="w", encoding="utf-8", newline="", delete=False, dir=path.parent, suffix=".tmp"
    ) as handle:
        temporary_path = Path(handle.name)
        handle.write(content)
    try:
        os.replace(temporary_path, path)
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Restore CSCO Tencent table OCR in Markdown and generate table-aware JSONL."
    )
    parser.add_argument("--source-markdown", required=True, type=Path)
    parser.add_argument("--tencent-json-dir", required=True, type=Path)
    parser.add_argument("--output-markdown", required=True, type=Path)
    parser.add_argument("--output-jsonl", required=True, type=Path)
    arguments = parser.parse_args()
    report = convert_csco_ocr(
        source_markdown=arguments.source_markdown,
        tencent_json_dir=arguments.tencent_json_dir,
        output_markdown=arguments.output_markdown,
        output_jsonl=arguments.output_jsonl,
    )
    print(
        " ".join(
            (
                f"markdown_replacements={report.markdown_replacements}",
                f"tables={report.table_count}",
                f"table_row_records={report.row_record_count}",
                f"text_records={report.text_record_count}",
                f"table_pages={report.page_count}",
            )
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
