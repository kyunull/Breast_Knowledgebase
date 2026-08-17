from __future__ import annotations

from dataclasses import dataclass
from math import isclose
from typing import Mapping, Sequence


@dataclass(frozen=True, slots=True)
class TableCell:
    row_tl: int
    col_tl: int
    row_br: int
    col_br: int
    text: str
    confidence: float | None


@dataclass(frozen=True, slots=True)
class TableGrid:
    cells: tuple[TableCell, ...]
    rows: int
    columns: int
    occupancy: tuple[tuple[TableCell | None, ...], ...]


@dataclass(frozen=True, slots=True)
class TableBox:
    page_number: int
    x0: float
    y0: float
    x1: float
    y1: float

    def __post_init__(self) -> None:
        if self.page_number < 1:
            raise ValueError("page_number must be one-based")
        if self.x1 <= self.x0 or self.y1 <= self.y0:
            raise ValueError("table box must have positive area")


def build_table_grid(table: Mapping[str, object]) -> TableGrid:
    raw_cells = table.get("Cells")
    if not isinstance(raw_cells, list) or not raw_cells:
        raise ValueError("table must contain at least one cell")

    cells: list[TableCell] = []
    for index, raw in enumerate(raw_cells, start=1):
        if not isinstance(raw, Mapping):
            raise ValueError(f"table cell {index} must be an object")
        row_tl = _required_int(raw, "RowTl", index)
        col_tl = _required_int(raw, "ColTl", index)
        row_br = _required_int(raw, "RowBr", index)
        col_br = _required_int(raw, "ColBr", index)
        if row_tl < 0 or col_tl < 0 or row_br <= row_tl or col_br <= col_tl:
            raise ValueError(f"table cell {index} has an invalid span")
        text = raw.get("Text", "")
        if not isinstance(text, str):
            raise ValueError(f"table cell {index} Text must be a string")
        confidence_value = raw.get("Confidence")
        confidence: float | None
        if confidence_value is None:
            confidence = None
        elif isinstance(confidence_value, (int, float)) and not isinstance(confidence_value, bool):
            confidence = float(confidence_value)
        else:
            raise ValueError(f"table cell {index} Confidence must be numeric")
        cells.append(
            TableCell(
                row_tl=row_tl,
                col_tl=col_tl,
                row_br=row_br,
                col_br=col_br,
                text=text,
                confidence=confidence,
            )
        )

    rows = max(cell.row_br for cell in cells)
    columns = max(cell.col_br for cell in cells)
    mutable: list[list[TableCell | None]] = [[None] * columns for _ in range(rows)]
    for cell in cells:
        for row_index in range(cell.row_tl, cell.row_br):
            for column_index in range(cell.col_tl, cell.col_br):
                if mutable[row_index][column_index] is not None:
                    raise ValueError(
                        f"table cells overlap at row {row_index + 1}, column {column_index + 1}"
                    )
                mutable[row_index][column_index] = cell

    return TableGrid(
        cells=tuple(cells),
        rows=rows,
        columns=columns,
        occupancy=tuple(tuple(row) for row in mutable),
    )


def linearize_table_rows(
    table: Mapping[str, object], *, table_title: str
) -> tuple[str, ...]:
    grid = build_table_grid(table)
    labels = _column_labels(grid)
    rows: list[str] = []
    for row_index in range(grid.rows):
        if row_index == 0:
            header_parts = _header_parts(grid)
            rows.append(f"表格：{table_title}\n表头：" + "；".join(header_parts))
            continue
        values = []
        for column_index, label in enumerate(labels):
            cell = grid.occupancy[row_index][column_index]
            value = "" if cell is None else _inline_text(cell.text)
            values.append(f"{label}={value}")
        rows.append(f"表格：{table_title}\n第{row_index + 1}行：" + "；".join(values))
    return tuple(rows)


def valid_tables(payload: Mapping[str, object]) -> tuple[Mapping[str, object], ...]:
    response = payload.get("Response")
    source: Mapping[str, object]
    if isinstance(response, Mapping):
        source = response
    else:
        source = payload
    detections = source.get("TableDetections", [])
    if not isinstance(detections, list):
        raise ValueError("TableDetections must be an array")
    result: list[Mapping[str, object]] = []
    for index, table in enumerate(detections, start=1):
        if not isinstance(table, Mapping):
            raise ValueError(f"TableDetections item {index} must be an object")
        if table.get("Type") in (1, 2, "1", "2"):
            result.append(table)
    return tuple(result)


def group_tables_by_boxes(
    boxes: Sequence[TableBox],
    tables: Sequence[Mapping[str, object]],
    *,
    page_number: int,
    minimum_overlap: float = 0.70,
) -> tuple[tuple[Mapping[str, object], ...], ...]:
    if not 0 < minimum_overlap <= 1:
        raise ValueError("minimum_overlap must be in (0, 1]")
    if any(box.page_number != page_number for box in boxes):
        raise ValueError(f"table box page mismatch for PDF page {page_number}")
    groups: list[list[Mapping[str, object]]] = [[] for _ in boxes]
    for table_index, table in enumerate(tables, start=1):
        table_rect = _table_rect(table)
        scores = [_overlap_ratio(_box_rect(box), table_rect) for box in boxes]
        if not scores or max(scores) < minimum_overlap:
            raise ValueError(
                f"Tencent table {table_index} on PDF page {page_number} does not match a candidate box"
            )
        best = max(scores)
        winners = [index for index, score in enumerate(scores) if isclose(score, best, abs_tol=1e-9)]
        if len(winners) != 1:
            raise ValueError(
                f"Tencent table {table_index} on PDF page {page_number} has ambiguous geometry"
            )
        groups[winners[0]].append(table)
    if any(not group for group in groups):
        missing = [str(index + 1) for index, group in enumerate(groups) if not group]
        raise ValueError(
            f"candidate table box(es) {', '.join(missing)} on PDF page {page_number} have no Tencent match"
        )
    return tuple(
        tuple(sorted(group, key=lambda table: (_table_rect(table)[1], _table_rect(table)[0])))
        for group in groups
    )


def make_table_records(
    *,
    table: Mapping[str, object],
    doc_id: str,
    doc_title: str,
    page_index: int,
    page_code: str | None,
    section_path: str,
    table_index: int,
    table_title: str,
    source_image: str,
) -> tuple[dict[str, object], ...]:
    if page_index < 0:
        raise ValueError("page_index must be zero-based and non-negative")
    if table_index < 1:
        raise ValueError("table_index must be one-based")
    grid = build_table_grid(table)
    rows = linearize_table_rows(table, table_title=table_title)
    table_id = f"{doc_id}_p{page_index + 1:03d}_t{table_index:02d}"
    confidences = [cell.confidence for cell in grid.cells if cell.confidence is not None]
    shared: dict[str, object] = {
        "doc_id": doc_id,
        "doc_title": doc_title,
        "section_path": section_path,
        "page_code": page_code,
        "page_start": page_index,
        "page_end": page_index,
        "table_id": table_id,
        "table_index": table_index,
        "table_title": table_title,
        "table_row_count": grid.rows,
        "table_column_count": grid.columns,
        "table_cell_count": len(grid.cells),
        "source_image": source_image,
        "ocr_confidence_min": min(confidences) if confidences else None,
        "ocr_confidence_mean": sum(confidences) / len(confidences) if confidences else None,
    }
    records: list[dict[str, object]] = [
        {
            **shared,
            "chunk_id": table_id,
            "block_type": "table",
            "text": "\n".join(rows),
        }
    ]
    for row_index, row_text in enumerate(rows, start=1):
        records.append(
            {
                **shared,
                "chunk_id": f"{table_id}_r{row_index:02d}",
                "block_type": "table_row",
                "text": row_text,
                "table_row_index": row_index,
                "parent_table_chunk_id": table_id,
            }
        )
    return tuple(records)


def _required_int(raw: Mapping[str, object], field: str, index: int) -> int:
    value = raw.get(field)
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"table cell {index} {field} must be an integer")
    return value


def _inline_text(value: str) -> str:
    return " ".join(part.strip() for part in value.splitlines() if part.strip())


def _header_parts(grid: TableGrid) -> list[str]:
    parts: list[str] = []
    seen: set[TableCell] = set()
    for column_index, cell in enumerate(grid.occupancy[0]):
        if cell is None or cell in seen:
            continue
        seen.add(cell)
        label = (
            f"第{cell.col_tl + 1}列"
            if cell.col_br - cell.col_tl == 1
            else f"第{cell.col_tl + 1}-{cell.col_br}列"
        )
        parts.append(f"{label}={_inline_text(cell.text)}")
    return parts


def _column_labels(grid: TableGrid) -> tuple[str, ...]:
    labels: list[str] = []
    counts: dict[str, int] = {}
    for column_index, cell in enumerate(grid.occupancy[0]):
        text = _inline_text(cell.text) if cell is not None else ""
        base = text or f"第{column_index + 1}列"
        counts[base] = counts.get(base, 0) + 1
        if cell is not None and cell.col_br - cell.col_tl > 1:
            labels.append(f"{base}（第{column_index + 1}列）")
        elif counts[base] > 1:
            labels.append(f"{base}（第{column_index + 1}列）")
        else:
            labels.append(base)
    return tuple(labels)


def _table_rect(table: Mapping[str, object]) -> tuple[float, float, float, float]:
    points = table.get("TableCoordPoint")
    if not isinstance(points, list) or len(points) < 2:
        raise ValueError("Tencent table geometry must contain at least two coordinate points")
    coordinates: list[tuple[float, float]] = []
    for point in points:
        if not isinstance(point, Mapping):
            raise ValueError("Tencent table coordinate point must be an object")
        x = point.get("X")
        y = point.get("Y")
        if (
            not isinstance(x, (int, float))
            or isinstance(x, bool)
            or not isinstance(y, (int, float))
            or isinstance(y, bool)
        ):
            raise ValueError("Tencent table coordinates must be numeric")
        coordinates.append((float(x), float(y)))
    x0 = min(x for x, _ in coordinates)
    y0 = min(y for _, y in coordinates)
    x1 = max(x for x, _ in coordinates)
    y1 = max(y for _, y in coordinates)
    if x1 <= x0 or y1 <= y0:
        raise ValueError("Tencent table geometry must have positive area")
    return x0, y0, x1, y1


def _box_rect(box: TableBox) -> tuple[float, float, float, float]:
    return box.x0, box.y0, box.x1, box.y1


def _overlap_ratio(
    first: tuple[float, float, float, float],
    second: tuple[float, float, float, float],
) -> float:
    intersection_width = max(0.0, min(first[2], second[2]) - max(first[0], second[0]))
    intersection_height = max(0.0, min(first[3], second[3]) - max(first[1], second[1]))
    intersection = intersection_width * intersection_height
    first_area = (first[2] - first[0]) * (first[3] - first[1])
    second_area = (second[2] - second[0]) * (second[3] - second[1])
    return intersection / min(first_area, second_area)
