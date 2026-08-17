from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from hashlib import sha256
import json
from pathlib import Path
import tempfile
from typing import Mapping, Sequence

import pymupdf

from scripts.table_ocr_core import TableBox, group_tables_by_boxes, make_table_records, valid_tables
from scripts.tencent_table_ocr import TencentTableOcrClient, resolve_credentials, write_response_atomic


@dataclass(frozen=True, slots=True)
class CandidatePage:
    page_index: int
    page_number: int
    image_name: str
    boxes: tuple[TableBox, ...]
    scaled_boxes: tuple[TableBox, ...]


@dataclass(frozen=True, slots=True)
class CandidateManifest:
    pdf_path: str
    page_count: int
    pages: tuple[CandidatePage, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "pdf_path": self.pdf_path,
            "page_count": self.page_count,
            "pages": [
                {
                    "page_index": page.page_index,
                    "page_number": page.page_number,
                    "image_name": page.image_name,
                    "boxes": [_box_to_dict(box) for box in page.boxes],
                    "scaled_boxes": [_box_to_dict(box) for box in page.scaled_boxes],
                }
                for page in self.pages
            ],
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> "CandidateManifest":
        raw_pages = payload.get("pages")
        if not isinstance(raw_pages, list):
            raise ValueError("candidate manifest pages must be an array")
        pages: list[CandidatePage] = []
        for raw_page in raw_pages:
            if not isinstance(raw_page, Mapping):
                raise ValueError("candidate manifest page must be an object")
            pages.append(
                CandidatePage(
                    page_index=int(raw_page["page_index"]),
                    page_number=int(raw_page["page_number"]),
                    image_name=str(raw_page["image_name"]),
                    boxes=tuple(_box_from_dict(raw_page["boxes"], int(raw_page["page_number"]))),
                    scaled_boxes=tuple(_box_from_dict(raw_page["scaled_boxes"], int(raw_page["page_number"]))),
                )
            )
        return cls(pdf_path=str(payload["pdf_path"]), page_count=int(payload["page_count"]), pages=tuple(pages))


@dataclass(frozen=True, slots=True)
class RebuildReport:
    status: str
    candidate_page_count: int
    baseline_table_count: int
    rebuilt_table_count: int
    rebuilt_row_count: int
    raw_cell_count: int
    retained_non_table_count: int
    baseline_non_table_sha256: str
    rebuilt_non_table_sha256: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def discover_candidates(pdf_path: Path, baseline_records: Sequence[dict[str, object]]) -> CandidateManifest:
    source = Path(pdf_path).resolve()
    if not source.is_file():
        raise FileNotFoundError(source)
    baseline_by_page: dict[int, int] = {}
    for record in baseline_records:
        if record.get("block_type") != "table":
            continue
        page_index = record.get("page_start")
        if not isinstance(page_index, int) or page_index < 0:
            raise ValueError("baseline table record has an invalid page_start")
        baseline_by_page[page_index] = baseline_by_page.get(page_index, 0) + 1

    pages: list[CandidatePage] = []
    with pymupdf.open(source) as document:
        page_count = document.page_count
        for page_index in range(document.page_count):
            page = document[page_index]
            finder = page.find_tables()
            found = list(getattr(finder, "tables", ()))
            found.sort(key=lambda table: (float(table.bbox[1]), float(table.bbox[0])))
            expected = baseline_by_page.get(page_index, 0)
            if len(found) != expected:
                if found or expected:
                    raise ValueError(
                        f"table count mismatch on PDF page {page_index + 1}: baseline={expected}, fresh_scan={len(found)}"
                    )
                continue
            if not found:
                continue
            boxes: list[TableBox] = []
            scaled: list[TableBox] = []
            for table in found:
                x0, y0, x1, y1 = map(float, table.bbox)
                boxes.append(TableBox(page_index + 1, x0, y0, x1, y1))
                scaled.append(TableBox(page_index + 1, x0 * 2, y0 * 2, x1 * 2, y1 * 2))
            pages.append(
                CandidatePage(
                    page_index=page_index,
                    page_number=page_index + 1,
                    image_name=f"source-page-{page_index + 1:03d}.png",
                    boxes=tuple(boxes),
                    scaled_boxes=tuple(scaled),
                )
            )
    if sum(len(page.boxes) for page in pages) != sum(baseline_by_page.values()):
        raise ValueError("table count mismatch between baseline and fresh scan")
    return CandidateManifest(pdf_path=str(source), page_count=page_count, pages=tuple(pages))


def render_candidate_pages(pdf_path: Path, manifest: CandidateManifest, output_dir: Path) -> None:
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    with pymupdf.open(Path(pdf_path)) as document:
        for candidate in manifest.pages:
            if candidate.page_index >= document.page_count:
                raise ValueError(f"candidate page index out of range: {candidate.page_index}")
            pixmap = document[candidate.page_index].get_pixmap(matrix=pymupdf.Matrix(2, 2), alpha=False)
            pixmap.save(destination / candidate.image_name)


def rebuild_jsonl(
    *,
    baseline_jsonl: Path,
    candidate_manifest: CandidateManifest,
    tencent_json_dir: Path,
    output_jsonl: Path,
    baseline_records: Sequence[dict[str, object]] | None = None,
) -> RebuildReport:
    baseline = list(baseline_records) if baseline_records is not None else _read_jsonl_objects(Path(baseline_jsonl))
    table_contexts: dict[int, list[dict[str, object]]] = {}
    for record in baseline:
        if record.get("block_type") == "table":
            page_index = record.get("page_start")
            if isinstance(page_index, int):
                table_contexts.setdefault(page_index, []).append(record)
    generated_by_page: dict[int, list[dict[str, object]]] = {}
    total_cells = 0
    rebuilt_tables = 0
    rebuilt_rows = 0
    for candidate in candidate_manifest.pages:
        contexts = table_contexts.get(candidate.page_index, [])
        if len(contexts) != len(candidate.boxes):
            raise ValueError(
                f"candidate page {candidate.page_number} has {len(candidate.boxes)} boxes but {len(contexts)} baseline tables"
            )
        raw_path = Path(tencent_json_dir) / candidate.image_name.replace(".png", ".json")
        if not raw_path.is_file():
            raise FileNotFoundError(raw_path)
        payload = _read_json_object(raw_path)
        tables = valid_tables(payload)
        groups = group_tables_by_boxes(candidate.scaled_boxes, tables, page_number=candidate.page_number)
        generated: list[dict[str, object]] = []
        table_index = 0
        for context, group in zip(contexts, groups, strict=True):
            for table in group:
                table_index += 1
                cell_count = table.get("Cells")
                total_cells += len(cell_count) if isinstance(cell_count, list) else 0
                generated_records = make_table_records(
                    table=table,
                    doc_id=str(context["doc_id"]),
                    doc_title=str(context["doc_title"]),
                    page_index=candidate.page_index,
                    page_code=context.get("page_code") if isinstance(context.get("page_code"), str) else None,
                    section_path=str(context.get("section_path", "")),
                    table_index=table_index,
                    table_title=str(context.get("table_title", "") or f"第{table_index}个表格"),
                    source_image=candidate.image_name,
                )
                generated.extend(generated_records)
                rebuilt_tables += 1
                rebuilt_rows += len(generated_records) - 1
        generated_by_page[candidate.page_index] = generated

    output: list[dict[str, object]] = []
    emitted_pages: set[int] = set()
    for record in baseline:
        block_type = record.get("block_type")
        if block_type == "table":
            page_index = record.get("page_start")
            if not isinstance(page_index, int) or page_index in emitted_pages:
                continue
            output.extend(generated_by_page.get(page_index, ()))
            emitted_pages.add(page_index)
        elif block_type == "table_row":
            continue
        else:
            output.append(record)
    if set(generated_by_page) != emitted_pages:
        missing = sorted(set(generated_by_page) - emitted_pages)
        raise ValueError(f"generated table pages were not found in baseline order: {missing}")
    non_table_baseline = [record for record in baseline if record.get("block_type") not in {"table", "table_row"}]
    non_table_output = [record for record in output if record.get("block_type") not in {"table", "table_row"}]
    baseline_hash = _records_text_hash(non_table_baseline)
    output_hash = _records_text_hash(non_table_output)
    report = RebuildReport(
        status="complete",
        candidate_page_count=len(candidate_manifest.pages),
        baseline_table_count=sum(len(value) for value in table_contexts.values()),
        rebuilt_table_count=rebuilt_tables,
        rebuilt_row_count=rebuilt_rows,
        raw_cell_count=total_cells,
        retained_non_table_count=len(non_table_output),
        baseline_non_table_sha256=baseline_hash,
        rebuilt_non_table_sha256=output_hash,
    )
    _write_jsonl_atomic(Path(output_jsonl), output)
    return report


def verify_rebuild(
    baseline_records: Sequence[dict[str, object]],
    rebuilt_records: Sequence[dict[str, object]],
    report: RebuildReport,
) -> dict[str, object]:
    baseline_non_tables = [record for record in baseline_records if record.get("block_type") not in {"table", "table_row"}]
    rebuilt_non_tables = [record for record in rebuilt_records if record.get("block_type") not in {"table", "table_row"}]
    if baseline_non_tables != rebuilt_non_tables:
        raise ValueError("non-table records changed during table rebuild")
    ids = [record.get("chunk_id") for record in rebuilt_records]
    if any(not isinstance(chunk_id, str) or not chunk_id for chunk_id in ids) or len(ids) != len(set(ids)):
        raise ValueError("rebuilt JSONL contains missing or duplicate chunk IDs")
    for record in rebuilt_records:
        if not isinstance(record.get("text"), str) or not isinstance(record.get("page_start"), int):
            raise ValueError("rebuilt record is missing required text/page fields")
    if report.baseline_non_table_sha256 != report.rebuilt_non_table_sha256:
        raise ValueError("non-table text hash changed during rebuild")
    return {**report.to_dict(), "status": "complete"}


def _read_jsonl_objects(path: Path) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    with path.open("r", encoding="utf-8", newline="") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                raise ValueError(f"empty JSONL line {line_number}")
            payload = json.loads(line)
            if not isinstance(payload, dict):
                raise ValueError(f"JSONL line {line_number} must be an object")
            records.append(payload)
    return records


def _read_json_object(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON payload must be an object: {path}")
    return payload


def _records_text_hash(records: Sequence[Mapping[str, object]]) -> str:
    digest = sha256()
    for record in records:
        text = record.get("text")
        if not isinstance(text, str):
            raise ValueError("record text must be a string")
        digest.update(text.encode("utf-8"))
        digest.update(b"\0")
    return digest.hexdigest()


def _write_jsonl_atomic(path: Path, records: Sequence[Mapping[str, object]]) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=destination.parent, prefix=f".{destination.name}.", suffix=".tmp", delete=False) as handle:
        temporary = Path(handle.name)
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
    temporary.replace(destination)


def _write_manifest(path: Path, manifest: CandidateManifest) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")


def _box_to_dict(box: TableBox) -> dict[str, object]:
    return {"page_number": box.page_number, "x0": box.x0, "y0": box.y0, "x1": box.x1, "y1": box.y1}


def _box_from_dict(payload: object, page_number: int) -> list[TableBox]:
    if not isinstance(payload, list):
        raise ValueError("candidate manifest boxes must be an array")
    boxes: list[TableBox] = []
    for raw in payload:
        if not isinstance(raw, Mapping):
            raise ValueError("candidate manifest box must be an object")
        boxes.append(TableBox(page_number, float(raw["x0"]), float(raw["y0"]), float(raw["x1"]), float(raw["y1"])))
    return boxes


def _load_manifest(path: Path) -> CandidateManifest:
    return CandidateManifest.from_dict(_read_json_object(path))


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Discover, OCR, and rebuild PDF table chunks")
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("prepare", "all"):
        sub = subparsers.add_parser(command)
        sub.add_argument("--pdf", required=True)
        sub.add_argument("--baseline-jsonl", required=True)
        sub.add_argument("--output-root", required=True)
        sub.add_argument("--output-jsonl", required=command == "all")
        sub.add_argument("--report")
    sub = subparsers.add_parser("ocr")
    sub.add_argument("--output-root", required=True)
    sub = subparsers.add_parser("rebuild")
    sub.add_argument("--baseline-jsonl", required=True)
    sub.add_argument("--output-root", required=True)
    sub.add_argument("--output-jsonl", required=True)
    sub.add_argument("--report")
    args = parser.parse_args(argv)
    root = Path(args.output_root).resolve()
    manifest_path = root / "candidate_manifest.json"
    pages_dir = root / "pages"
    raw_dir = root / "raw"
    if args.command in {"prepare", "all"}:
        baseline = _read_jsonl_objects(Path(args.baseline_jsonl))
        manifest = discover_candidates(Path(args.pdf), baseline)
        _write_manifest(manifest_path, manifest)
        render_candidate_pages(Path(args.pdf), manifest, pages_dir)
    if args.command in {"ocr", "all"}:
        manifest = _load_manifest(manifest_path)
        raw_dir.mkdir(parents=True, exist_ok=True)
        client = TencentTableOcrClient(resolve_credentials())
        for candidate in manifest.pages:
            raw_path = raw_dir / candidate.image_name.replace(".png", ".json")
            if raw_path.is_file():
                try:
                    payload = _read_json_object(raw_path)
                    if valid_tables(payload):
                        continue
                except (OSError, ValueError, json.JSONDecodeError):
                    pass
            payload = client.recognize_png(pages_dir / candidate.image_name)
            write_response_atomic(raw_path, payload)
            print(f"OCR completed: {candidate.image_name}")
    if args.command in {"rebuild", "all"}:
        baseline_path = Path(args.baseline_jsonl)
        baseline = _read_jsonl_objects(baseline_path)
        manifest = _load_manifest(manifest_path)
        report = rebuild_jsonl(
            baseline_jsonl=baseline_path,
            baseline_records=baseline,
            candidate_manifest=manifest,
            tencent_json_dir=raw_dir,
            output_jsonl=Path(args.output_jsonl),
        )
        rebuilt = _read_jsonl_objects(Path(args.output_jsonl))
        result = verify_rebuild(baseline, rebuilt, report)
        report_path = Path(args.report) if args.report else root / "rebuild_report.json"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
