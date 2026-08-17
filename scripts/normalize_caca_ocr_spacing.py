"""Normalize deterministic OCR spacing defects in the CACA chunk source.

The input source is preserved.  This module emits a new JSONL and an audit
report so an existing immutable snapshot is never modified in place.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass
from hashlib import sha256
import json
from pathlib import Path
import re
import tempfile
from typing import Mapping


_WHITESPACE = r"[ \t\u2003\u00a0]+"


@dataclass(frozen=True, slots=True)
class _Rule:
    id: str
    source: str
    target: str
    pattern: re.Pattern[str]


def _rule(rule_id: str, source: str, target: str) -> _Rule:
    escaped = re.escape(source).replace(r"\ ", _WHITESPACE)
    return _Rule(rule_id, source, target, re.compile(escaped))


# Rules are intentionally explicit.  Bibliographic initials and figure labels
# remain spaced because a generic "join letters" pass would corrupt them.
_RULES = (
    _rule(
        "maximum_intensity",
        "m a x i m u m i n t e n s i t y",
        "maximum intensity",
    ),
    _rule(
        "apparent_diffusion",
        "a p p a r e n t d i f f u s i o n",
        "apparent diffusion",
    ),
    _rule("split_tumor", "t u m o r", "tumor"),
    _rule("split_local", "l o c a l", "local"),
    _rule("split_anti", "a n t i -", "anti-"),
    _rule("split_cancer", "c a n c e r", "cancer"),
    _rule("split_tcb", "T C b", "TCb"),
    _rule("split_her2", "H E R 2", "HER2"),
    _rule("split_cdk4_6", "C D K 4 / 6", "CDK4/6"),
    _rule("split_bmi", "B M I", "BMI"),
    _rule("split_36_ku", "3 6 k U", "36 kU"),
    _rule("split_ku", "k U", "kU"),
    _rule("split_prepare_registration", "P R E P A R E - ", "PREPARE-"),
    _rule("split_prepare", "P R E P A R E", "PREPARE"),
    _rule("split_nci_ctcae", "N C I -C T C A E 5 . 0", "NCI-CTCAE 5.0"),
    _rule("split_mg_kg", "m g / k g", "mg/kg"),
    _rule(
        "split_bibliographic_surnames",
        "B L O K E J , K R O E P J R , M E E R S H O E K - K L E I N KRANENBARG E",
        "BLOK E J, KROEP J R, MEERSHOEK-KLEIN KRANENBARG E",
    ),
)

# This detector is deliberately narrower than the replacement rules.  It is
# used as a post-condition for lower-case English words only; author initials
# and diagram labels are legitimate spaced tokens in this corpus.
_LOWERCASE_SPLIT_RE = re.compile(
    rf"(?<![A-Za-z])(?:[a-z]{_WHITESPACE}){{1,}}[a-z](?![A-Za-z])"
)


@dataclass(frozen=True, slots=True)
class NormalizedText:
    text: str
    replacements: Mapping[str, int]

    @property
    def replacement_count(self) -> int:
        return sum(self.replacements.values())


@dataclass(frozen=True, slots=True)
class NormalizationReport:
    status: str
    input_jsonl: str
    output_jsonl: str
    input_jsonl_sha256: str
    output_jsonl_sha256: str
    record_count: int
    affected_record_count: int
    unchanged_record_count: int
    replacement_count: int
    replacements_by_rule: Mapping[str, int]
    residual_lowercase_split_count: int

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def find_suspicious_spacing(text: str) -> tuple[str, ...]:
    """Return lower-case words that are still split into isolated letters."""

    return tuple(match.group(0) for match in _LOWERCASE_SPLIT_RE.finditer(text))


def normalize_caca_ocr_spacing(text: str) -> NormalizedText:
    if not isinstance(text, str):
        raise TypeError("text must be a string")
    replacements: Counter[str] = Counter()
    normalized = text
    for rule in _RULES:
        normalized, count = rule.pattern.subn(rule.target, normalized)
        if count:
            replacements[rule.id] += count
    return NormalizedText(normalized, dict(replacements))


def normalize_caca_jsonl(
    *, input_jsonl: Path, output_jsonl: Path, report_path: Path
) -> NormalizationReport:
    source = Path(input_jsonl).resolve()
    destination = Path(output_jsonl).resolve()
    report_destination = Path(report_path).resolve()
    if not source.is_file():
        raise FileNotFoundError(source)
    if source == destination:
        raise ValueError("input and output JSONL paths must be different")

    records: list[dict[str, object]] = []
    replacements: Counter[str] = Counter()
    affected = 0
    residual_count = 0
    with source.open("r", encoding="utf-8", newline="") as handle:
        for line_number, line in enumerate(handle, start=1):
            if line.strip("\r\n") == "":
                raise ValueError(f"line {line_number}: empty JSONL record")
            try:
                record = json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(f"line {line_number}: invalid JSON: {error.msg}") from error
            if not isinstance(record, dict) or not isinstance(record.get("text"), str):
                raise ValueError(f"line {line_number}: record must contain string text")
            normalized = normalize_caca_ocr_spacing(record["text"])
            if normalized.text != record["text"]:
                affected += 1
                record = dict(record)
                record["text"] = normalized.text
            replacements.update(normalized.replacements)
            residual_count += len(find_suspicious_spacing(normalized.text))
            records.append(record)

    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", newline="\n", dir=destination.parent,
        prefix=f".{destination.name}.", suffix=".tmp", delete=False,
    ) as handle:
        temporary = Path(handle.name)
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")))
            handle.write("\n")
    temporary.replace(destination)

    report = NormalizationReport(
        status="complete",
        input_jsonl=str(source),
        output_jsonl=str(destination),
        input_jsonl_sha256=_sha256(source),
        output_jsonl_sha256=_sha256(destination),
        record_count=len(records),
        affected_record_count=affected,
        unchanged_record_count=len(records) - affected,
        replacement_count=sum(replacements.values()),
        replacements_by_rule=dict(sorted(replacements.items())),
        residual_lowercase_split_count=residual_count,
    )
    report_destination.parent.mkdir(parents=True, exist_ok=True)
    report_destination.write_text(
        json.dumps(report.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return report


def _sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Normalize CACA OCR English spacing")
    parser.add_argument("--input-jsonl", required=True, type=Path)
    parser.add_argument("--output-jsonl", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    arguments = parser.parse_args()
    report = normalize_caca_jsonl(
        input_jsonl=arguments.input_jsonl,
        output_jsonl=arguments.output_jsonl,
        report_path=arguments.report,
    )
    print(json.dumps(report.to_dict(), ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
