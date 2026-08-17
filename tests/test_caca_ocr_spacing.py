from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path

from scripts.normalize_caca_ocr_spacing import (
    find_suspicious_spacing,
    normalize_caca_jsonl,
    normalize_caca_ocr_spacing,
)


def test_normalizes_split_english_terms_without_merging_word_boundaries() -> None:
    source = (
        "最大信号投影（m a x i m u m i n t e n s i t y projection，MIP）；"
        "表观扩散系数（a p p a r e n t d i f f u s i o n coefficient，ADC）；"
        "t u m o r infiltrating lymphocyte；l o c a l recurrence；"
        "a n t i -neoplastic treatment；c a n c e r treatment-related dysfunction。"
    )

    result = normalize_caca_ocr_spacing(source)

    assert result.text == (
        "最大信号投影（maximum intensity projection，MIP）；"
        "表观扩散系数（apparent diffusion coefficient，ADC）；"
        "tumor infiltrating lymphocyte；local recurrence；"
        "anti-neoplastic treatment；cancer treatment-related dysfunction。"
    )
    assert result.replacement_count == 6
    assert find_suspicious_spacing(result.text) == ()


def test_normalizes_known_acronyms_and_units_but_preserves_reference_initials() -> None:
    source = (
        "T C b ＋抗H E R 2治疗；C D K 4 / 6抑制剂；B M I；"
        "N C I -C T C A E 5 . 0；3 6 k U；6 m g / k g；"
        "P R E P A R E - 2025CN2010。"
        "JOHNSTON S R D, MORAN M S。图示 A B C D E。"
    )

    result = normalize_caca_ocr_spacing(source)

    assert result.text == (
        "TCb ＋抗HER2治疗；CDK4/6抑制剂；BMI；"
        "NCI-CTCAE 5.0；36 kU；6 mg/kg；"
        "PREPARE-2025CN2010。"
        "JOHNSTON S R D, MORAN M S。图示 A B C D E。"
    )
    assert "JOHNSTON S R D" in result.text
    assert "A B C D E" in result.text


def test_normalizes_split_bibliographic_surnames_without_collapsing_initials() -> None:
    source = (
        "B L O K E J , K R O E P J R , "
        "M E E R S H O E K - K L E I N KRANENBARG E, et al."
    )

    result = normalize_caca_ocr_spacing(source)

    assert result.text == (
        "BLOK E J, KROEP J R, MEERSHOEK-KLEIN KRANENBARG E, et al."
    )


def test_leaves_normal_english_chinese_numbers_and_units_unchanged() -> None:
    source = (
        "contrast-enhanced MRI and apparent diffusion coefficient，"
        "剂量0.1~0.2 mmol/kg，JOHNSTON S R D。"
    )

    result = normalize_caca_ocr_spacing(source)

    assert result.text == source
    assert result.replacement_count == 0


def test_normalize_jsonl_preserves_structure_and_writes_audit_report(tmp_path: Path) -> None:
    source_path = tmp_path / "source.jsonl"
    output_path = tmp_path / "normalized.jsonl"
    report_path = tmp_path / "report.json"
    records = [
        {"chunk_id": "a", "text": "m a x i m u m i n t e n s i t y projection", "page_start": 1},
        {"chunk_id": "b", "text": "正常文本 MRI", "page_start": 2},
    ]
    source_path.write_text(
        "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records),
        encoding="utf-8",
        newline="\n",
    )

    report = normalize_caca_jsonl(
        input_jsonl=source_path,
        output_jsonl=output_path,
        report_path=report_path,
    )

    normalized = [json.loads(line) for line in output_path.read_text(encoding="utf-8").splitlines()]
    assert normalized == [
        {"chunk_id": "a", "text": "maximum intensity projection", "page_start": 1},
        records[1],
    ]
    assert report.record_count == 2
    assert report.affected_record_count == 1
    assert report.unchanged_record_count == 1
    assert report.replacement_count == 1
    assert report.input_jsonl_sha256 == sha256(source_path.read_bytes()).hexdigest()
    assert report.output_jsonl_sha256 == sha256(output_path.read_bytes()).hexdigest()
    assert json.loads(report_path.read_text(encoding="utf-8"))["status"] == "complete"
