from __future__ import annotations

from hashlib import sha256
import json

import pytest

from app.contracts import RawChunkRecord
from app.terminology import (
    DEFAULT_SEED_TERMS,
    audit_bilingual_dictionary,
    build_bilingual_dictionary,
    expand_query,
    load_or_build_dictionary,
    tokenize_query,
)


def _raw_chunk(text: str, chunk_id: str = "chunk-1") -> RawChunkRecord:
    locator = {
        "chunk_id": chunk_id,
        "doc_id": "fixture",
        "doc_title": "fixture",
        "section_path": "fixture",
        "page_code": "1",
        "page_start": 0,
        "page_end": 0,
        "block_type": "text",
        "text": text,
    }
    return RawChunkRecord(
        id=f"fixture:{chunk_id}",
        source_file_id="fixture-source",
        source_ordinal=1,
        chunk_id=chunk_id,
        text=text,
        content_sha256=sha256(text.encode("utf-8")).hexdigest(),
        locator_json=json.dumps(locator, ensure_ascii=False),
    )


def test_tokenize_query_emits_chinese_ngrams_and_preserves_english_terms():
    tokens = tokenize_query("复发转移 therapy T-DXd 2.5mg")

    assert {"复发", "发转", "转移", "therapy", "t-dxd", "2.5mg"}.issubset(tokens)


def test_expand_query_longest_match_handles_multiple_separated_keywords():
    terms = {
        "复发转移": ("recurrent metastatic breast cancer",),
        "疗法": ("therapy", "treatment"),
    }

    expanded = expand_query("复发转移 疗法", terms)

    assert expanded.startswith("复发转移 疗法")
    assert "recurrent metastatic breast cancer" in expanded
    assert "therapy" in expanded and "treatment" in expanded


def test_expand_query_suppresses_nested_chinese_terms():
    terms = {
        "复发": ("recurrence",),
        "转移": ("metastasis",),
        "复发转移": ("recurrent metastatic",),
        "疗法": ("therapy",),
    }

    expanded = expand_query("复发转移 疗法", terms)

    assert "recurrent metastatic" in expanded
    assert "therapy" in expanded
    assert "recurrence" not in expanded
    assert "metastasis" not in expanded.split()


def test_expand_query_does_not_expand_ambiguous_ascii_abbreviation():
    terms = {
        "ADC": ("抗体药物偶联物", "表观扩散系数"),
        "抗体药物偶联物": ("ADC",),
        "表观扩散系数": ("ADC",),
    }

    assert expand_query("ADC", terms) == "ADC"


def test_expand_query_does_not_expand_lowercase_ambiguous_ascii_abbreviation():
    terms = {
        "adc": ("抗体药物偶联物", "表观扩散系数"),
        "抗体药物偶联物": ("adc",),
        "表观扩散系数": ("adc",),
    }

    assert expand_query("adc", terms) == "adc"


def test_expand_query_does_not_match_ascii_key_inside_another_token():
    terms = {
        "HER2阳性": ("HER2-positive",),
        "ER": ("雌激素受体",),
    }

    expanded = expand_query("HER2阳性", terms)

    assert "HER2-positive" in expanded
    assert "雌激素受体" not in expanded


def test_build_dictionary_extracts_parenthesized_bilingual_terms_and_reverse_aliases():
    chunks = [_raw_chunk("表观扩散系数（apparent diffusion coefficient，ADC）和乳腺癌治疗")]

    terms = build_bilingual_dictionary(chunks, seed_terms={})

    assert "apparent diffusion coefficient" in terms["表观扩散系数"]
    assert "表观扩散系数" in terms["ADC"]


def test_build_dictionary_rejects_structurally_valid_but_unreviewed_pair():
    terms = build_bilingual_dictionary(
        [_raw_chunk("虚构术语（invented clinical term）")],
        seed_terms={},
    )

    assert terms == {}


def test_build_dictionary_ignores_numeric_dose_parentheses():
    terms = build_bilingual_dictionary([_raw_chunk("建议钙（1 000 mg/d）")], seed_terms={})

    assert "建议钙" not in terms


def test_build_dictionary_rejects_measurement_unit_parenthetical_alias():
    terms = build_bilingual_dictionary(
        [_raw_chunk("LDL-C理想水平：4.9 mmol/L（高危）")],
        seed_terms={},
    )

    assert "mmol/L" not in terms
    assert "高危" not in terms


def test_build_dictionary_rejects_sentence_fragment_parenthetical_alias():
    terms = build_bilingual_dictionary(
        [_raw_chunk("digital mammography（如果后续诊断性数字乳腺X线摄影）")],
        seed_terms={},
    )

    assert "digital mammography" not in terms


def test_build_dictionary_rejects_contextual_chinese_clause():
    terms = build_bilingual_dictionary(
        [_raw_chunk("焦虑量表包括医院焦虑抑郁量表（HADS）")],
        seed_terms={},
    )

    assert "HADS" not in terms


def test_build_dictionary_rejects_chinese_ocr_fragment_with_ascii_context():
    terms = build_bilingual_dictionary(
        [_raw_chunk("仅依据SLNB分期或SLN加非前哨淋巴结（non-SLN，nSLN）")],
        seed_terms={},
    )

    assert "non-SLN" not in terms
    assert "nSLN" not in terms


def test_build_dictionary_rejects_identifier_and_threshold_aliases():
    terms = build_bilingual_dictionary(
        [_raw_chunk("ORCID: 0000-0001-7241-0760（张瑾）")],
        seed_terms={},
    )

    assert "ORCID: 0000-0001-7241-0760" not in terms


def test_default_seeds_cover_lymph_node_metastasis_and_high_risk():
    terms = build_bilingual_dictionary([], seed_terms=DEFAULT_SEED_TERMS)

    assert set(terms["淋巴转移"]) == {"lymph node metastasis", "nodal metastasis"}
    assert set(terms["高危"]) == {"high risk", "high-risk"}


def test_build_dictionary_rejects_forbidden_custom_seed():
    with pytest.raises(ValueError, match="measurement_or_threshold"):
        build_bilingual_dictionary([], seed_terms={"高危": ("mmol/L",)})


def test_generic_prognostic_index_does_not_expand_to_van_nuys_index():
    terms = build_bilingual_dictionary([], seed_terms=DEFAULT_SEED_TERMS)

    assert "van Nuys prognostic index" not in expand_query("预后指数", terms)


def test_van_nuys_prognostic_index_has_explicit_mapping():
    terms = build_bilingual_dictionary([], seed_terms=DEFAULT_SEED_TERMS)

    assert "van Nuys prognostic index" in expand_query("Van Nuys预后指数", terms)
    assert "Van Nuys预后指数" in expand_query("VNPI", terms)


def test_query_expansion_never_adds_measurement_unit_from_source_noise():
    terms = build_bilingual_dictionary(
        [_raw_chunk("4.9 mmol/L（高危）")],
        seed_terms=DEFAULT_SEED_TERMS,
    )

    expanded = expand_query("淋巴转移 高危", terms)

    assert "lymph node metastasis" in expanded
    assert "high risk" in expanded
    assert "mmol/L" not in expanded


def test_conflicting_auto_alias_is_removed_but_reviewed_mapping_remains():
    chunks = [
        _raw_chunk(
            "选择性雌激素受体调节剂（selective estrogen receptor modulator，SERM）",
            "correct",
        ),
        _raw_chunk(
            "选择性雌激素受体降解剂（selective estrogen receptor modulator，SERD）",
            "conflict",
        ),
    ]
    seeds = {
        "选择性雌激素受体调节剂": (
            "selective estrogen receptor modulator",
            "SERM",
        ),
        "选择性雌激素受体降解剂": (
            "selective estrogen receptor degrader",
            "SERD",
        ),
    }

    terms = build_bilingual_dictionary(chunks, seed_terms=seeds)

    assert terms["selective estrogen receptor modulator"] == (
        "选择性雌激素受体调节剂",
    )
    assert "选择性雌激素受体降解剂" not in terms[
        "selective estrogen receptor modulator"
    ]


def test_load_or_build_dictionary_reuses_matching_source_fingerprint(tmp_path):
    path = tmp_path / "bilingual_terms.json"
    chunks = [_raw_chunk("乳腺癌（breast cancer）")]

    first = load_or_build_dictionary(path, chunks, ["csco-r1"], seed_terms={})
    second = load_or_build_dictionary(path, chunks, ["csco-r1"], seed_terms={})

    assert first == second
    assert path.exists()


def test_load_or_build_dictionary_writes_rejection_audit(tmp_path):
    path = tmp_path / "bilingual_terms.json"
    chunks = [
        _raw_chunk("乳腺癌（breast cancer）", "valid"),
        _raw_chunk("4.9 mmol/L（高危）", "invalid"),
    ]

    load_or_build_dictionary(path, chunks, ["csco-r1"], seed_terms={})

    audit_path = tmp_path / "bilingual_terms.audit.json"
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    assert audit["source_version_ids"] == ["csco-r1"]
    assert audit["accepted_pair_count"] == 1
    assert audit["rejected_candidate_count"] == 1
    assert audit["rejected_candidates"] == [
        {
            "chunk_id": "invalid",
            "reason": "measurement_or_threshold",
            "source": "mmol/L",
            "target": "高危",
        }
    ]


def test_load_or_build_dictionary_rebuilds_when_audit_metadata_is_stale(tmp_path):
    path = tmp_path / "bilingual_terms.json"
    chunks = [_raw_chunk("乳腺癌（breast cancer）")]

    load_or_build_dictionary(path, chunks, ["csco-r1"], seed_terms={})
    audit_path = tmp_path / "bilingual_terms.audit.json"
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    audit["source_fingerprint"] = "stale"
    audit_path.write_text(json.dumps(audit, ensure_ascii=False), encoding="utf-8")

    load_or_build_dictionary(path, chunks, ["csco-r1"], seed_terms={})

    rebuilt = json.loads(audit_path.read_text(encoding="utf-8"))
    assert rebuilt["source_fingerprint"] != "stale"


def test_load_or_build_dictionary_rebuilds_when_audit_content_is_corrupted(tmp_path):
    path = tmp_path / "bilingual_terms.json"
    chunks = [_raw_chunk("乳腺癌（breast cancer）")]

    load_or_build_dictionary(path, chunks, ["csco-r1"], seed_terms={})
    audit_path = tmp_path / "bilingual_terms.audit.json"
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    audit["reviewed_seeds"] = {"tampered": ["term"]}
    audit_path.write_text(json.dumps(audit, ensure_ascii=False), encoding="utf-8")

    load_or_build_dictionary(path, chunks, ["csco-r1"], seed_terms={})

    rebuilt = json.loads(audit_path.read_text(encoding="utf-8"))
    assert rebuilt["reviewed_seeds"] == {}


def test_load_or_build_dictionary_rebuilds_corrupted_cached_terms(tmp_path):
    path = tmp_path / "bilingual_terms.json"
    chunks = [_raw_chunk("乳腺癌（breast cancer）")]

    load_or_build_dictionary(path, chunks, ["csco-r1"], seed_terms={})
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["terms"] = {"高危": ["mmol/L"], "mmol/L": ["高危"]}
    payload["term_count"] = 2
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    terms = load_or_build_dictionary(path, chunks, ["csco-r1"], seed_terms={})

    assert "mmol/L" not in terms


def test_load_or_build_dictionary_rebuilds_empty_cached_term_values(tmp_path):
    path = tmp_path / "bilingual_terms.json"
    chunks = [_raw_chunk("乳腺癌（breast cancer）")]

    load_or_build_dictionary(path, chunks, ["csco-r1"], seed_terms={})
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["terms"] = {"乳腺癌": []}
    payload["term_count"] = 1
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    terms = load_or_build_dictionary(path, chunks, ["csco-r1"], seed_terms={})

    assert terms["乳腺癌"] == ("breast cancer",)


def test_audit_bilingual_dictionary_rejects_forbidden_and_nonreciprocal_pairs():
    errors = audit_bilingual_dictionary(
        {
            "mmol/L": ("高危",),
            "乳腺癌": ("breast cancer",),
            "breast cancer": (),
        }
    )

    assert any("forbidden" in error for error in errors)
    assert any("non-reciprocal" in error for error in errors)


def test_audit_bilingual_dictionary_rejects_reciprocal_sentence_fragment():
    errors = audit_bilingual_dictionary(
        {
            "foo": ("高危患者",),
            "高危患者": ("foo",),
        }
    )

    assert any("sentence_fragment" in error for error in errors)
