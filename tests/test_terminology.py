from __future__ import annotations

from hashlib import sha256
import json

from app.contracts import RawChunkRecord
from app.terminology import (
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


def test_build_dictionary_extracts_parenthesized_bilingual_terms_and_reverse_aliases():
    chunks = [_raw_chunk("表观扩散系数（apparent diffusion coefficient，ADC）和乳腺癌治疗")]

    terms = build_bilingual_dictionary(chunks, seed_terms={})

    assert "apparent diffusion coefficient" in terms["表观扩散系数"]
    assert "表观扩散系数" in terms["ADC"]


def test_load_or_build_dictionary_reuses_matching_source_fingerprint(tmp_path):
    path = tmp_path / "bilingual_terms.json"
    chunks = [_raw_chunk("乳腺癌（breast cancer）")]

    first = load_or_build_dictionary(path, chunks, ["csco-r1"], seed_terms={})
    second = load_or_build_dictionary(path, chunks, ["csco-r1"], seed_terms={})

    assert first == second
    assert path.exists()
