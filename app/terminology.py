from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import re
from typing import Iterable, Mapping, Sequence
from uuid import uuid4

from app.contracts import RawChunkRecord


DEFAULT_SEED_TERMS: dict[str, tuple[str, ...]] = {
    "乳腺癌": ("breast cancer",),
    "复发": ("recurrent", "recurrence"),
    "转移": ("metastatic", "metastasis"),
    "复发转移": ("recurrent metastatic", "recurrent or metastatic"),
    "复发转移性乳腺癌": ("recurrent metastatic breast cancer",),
    "晚期乳腺癌": ("advanced breast cancer",),
    "转移性乳腺癌": ("metastatic breast cancer",),
    "疗法": ("therapy", "treatment"),
    "治疗": ("treatment", "therapy"),
    "手术": ("surgery", "operation"),
    "新辅助治疗": ("neoadjuvant therapy", "preoperative therapy"),
    "辅助治疗": ("adjuvant therapy",),
    "化疗": ("chemotherapy",),
    "内分泌治疗": ("endocrine therapy",),
    "免疫治疗": ("immunotherapy",),
    "放疗": ("radiotherapy", "radiation therapy"),
    "靶向治疗": ("targeted therapy",),
    "HER2阳性": ("HER2-positive",),
    "激素受体阳性": ("hormone receptor-positive", "HR-positive"),
    "三阴性乳腺癌": ("triple-negative breast cancer", "TNBC"),
    "曲妥珠单抗": ("trastuzumab",),
    "帕妥珠单抗": ("pertuzumab",),
    "德曲妥珠单抗": ("trastuzumab deruxtecan", "T-DXd"),
    "恩美曲妥珠单抗": ("ado-trastuzumab emtansine", "T-DM1"),
    "吡咯替尼": ("pyrotinib",),
    "拉帕替尼": ("lapatinib",),
    "奈拉替尼": ("neratinib",),
    "多西他赛": ("docetaxel",),
    "紫杉醇": ("paclitaxel",),
    "白蛋白紫杉醇": ("nab-paclitaxel",),
    "卡培他滨": ("capecitabine",),
    "奥拉帕利": ("olaparib",),
    "不良反应": ("adverse events", "toxicity"),
    "疗效": ("efficacy",),
    "剂量": ("dose", "dosing"),
    "风险": ("risk",),
}

_SCHEMA_VERSION = 2
_ASCII_TOKEN = re.compile(r"[A-Za-z0-9]+(?:[./+_-][A-Za-z0-9]+)*")
_CHINESE_RUN = re.compile(r"[\u3400-\u9fff]+")
_ZH_PAREN = re.compile(
    r"(?P<zh>[\u3400-\u9fff][\u3400-\u9fffA-Za-z0-9·\-]{1,24})"
    r"\s*[（(]\s*(?P<inside>[^（）()]{2,100})[）)]"
)
_EN_PAREN = re.compile(
    r"(?P<en>[A-Za-z][A-Za-z0-9 .+/_\-]{1,79})"
    r"\s*[（(]\s*(?P<zh>[\u3400-\u9fff]{2,24})[）)]"
)


def tokenize_query(text: str) -> tuple[str, ...]:
    """Tokenize bilingual text with Chinese character n-grams.

    Chinese runs emit overlapping bigrams and trigrams. ASCII terms retain
    medication names, abbreviations, decimals, and hyphenated forms.
    """
    tokens: list[str] = []
    positions: list[tuple[int, int, str]] = []
    for match in _CHINESE_RUN.finditer(text):
        positions.append((match.start(), match.end(), "zh"))
    for match in _ASCII_TOKEN.finditer(text):
        positions.append((match.start(), match.end(), "ascii"))

    for start, end, kind in sorted(positions):
        value = text[start:end]
        if kind == "ascii":
            tokens.append(value.casefold())
            continue
        if len(value) == 1:
            tokens.append(value)
            continue
        tokens.extend(value[index : index + 2] for index in range(len(value) - 1))
        if len(value) >= 3:
            tokens.extend(value[index : index + 3] for index in range(len(value) - 2))
    return tuple(tokens)


def expand_query(query: str, terms: Mapping[str, Sequence[str]]) -> str:
    """Append longest-matched local aliases while retaining the original query."""
    original = " ".join(query.strip().split())
    if not original:
        return original

    expanded: list[str] = [original]
    seen = {original.casefold()}
    lowered = original.casefold()
    keys = sorted((key for key in terms if key.strip()), key=lambda key: (-len(key), key.casefold(), key))
    for key in keys:
        if key.casefold() not in lowered:
            continue
        for alias in terms[key]:
            cleaned = " ".join(str(alias).split())
            if not cleaned or cleaned.casefold() in seen:
                continue
            expanded.append(cleaned)
            seen.add(cleaned.casefold())
    return " ".join(expanded)


def build_bilingual_dictionary(
    chunks: Iterable[RawChunkRecord],
    seed_terms: Mapping[str, Sequence[str]] | None = None,
) -> dict[str, tuple[str, ...]]:
    """Build a deterministic bidirectional glossary from local source text."""
    aliases: dict[str, set[str]] = {}

    for source, values in (seed_terms or {}).items():
        for value in values:
            _add_alias(aliases, source, value)

    for chunk in chunks:
        text = chunk.text
        for match in _ZH_PAREN.finditer(text):
            chinese = _clean_term(match.group("zh"))
            if not 2 <= len(chinese) <= 16:
                continue
            for alias in _split_aliases(match.group("inside")):
                _add_alias(aliases, chinese, alias)
        for match in _EN_PAREN.finditer(text):
            english = _clean_term(match.group("en"))
            chinese = _clean_term(match.group("zh"))
            if _is_english_alias(english):
                _add_alias(aliases, english, chinese)

    return {
        key: tuple(sorted(values, key=lambda value: (value.casefold(), value)))
        for key, values in sorted(aliases.items(), key=lambda item: (item[0].casefold(), item[0]))
        if values
    }


def load_or_build_dictionary(
    path: Path,
    chunks: Iterable[RawChunkRecord],
    source_version_ids: Sequence[str],
    seed_terms: Mapping[str, Sequence[str]] | None = None,
) -> dict[str, tuple[str, ...]]:
    """Load a matching glossary or atomically rebuild it from local chunks."""
    materialized = list(chunks)
    normalized_seeds = _normalize_terms(seed_terms or {})
    source_fingerprint = _source_fingerprint(materialized, source_version_ids, normalized_seeds)
    destination = Path(path)

    cached = _read_cached_terms(destination, source_version_ids, source_fingerprint)
    if cached is not None:
        return cached

    terms = build_bilingual_dictionary(materialized, normalized_seeds)
    payload = {
        "schema_version": _SCHEMA_VERSION,
        "source_version_ids": sorted(set(source_version_ids)),
        "source_fingerprint": source_fingerprint,
        "term_count": len(terms),
        "terms": {key: list(values) for key, values in terms.items()},
    }
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.{uuid4().hex}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    temporary.replace(destination)
    return terms


def _add_alias(aliases: dict[str, set[str]], source: str, target: str) -> None:
    source = _clean_term(source)
    target = _clean_term(target)
    if not source or not target or source.casefold() == target.casefold():
        return
    aliases.setdefault(source, set()).add(target)
    aliases.setdefault(target, set()).add(source)


def _split_aliases(value: str) -> list[str]:
    pieces = re.split(r"[，,;；]", value)
    return [
        cleaned
        for piece in pieces
        if (cleaned := _clean_term(piece)) and _is_english_alias(cleaned)
    ]


def _clean_term(value: str) -> str:
    return " ".join(value.strip(" \t\r\n:：;；,，") .split())


def _is_english_alias(value: str) -> bool:
    if len(value) > 80 or not re.match(r"^[A-Za-z]", value):
        return False
    if not re.search(r"[A-Za-z]{2}", value):
        return False
    return not any("\u3400" <= character <= "\u9fff" for character in value)


def _normalize_terms(terms: Mapping[str, Sequence[str]]) -> dict[str, tuple[str, ...]]:
    normalized: dict[str, tuple[str, ...]] = {}
    for key, values in terms.items():
        cleaned_key = _clean_term(str(key))
        cleaned_values = tuple(
            sorted(
                {
                    _clean_term(str(value))
                    for value in values
                    if _clean_term(str(value))
                },
                key=lambda value: (value.casefold(), value),
            )
        )
        if cleaned_key and cleaned_values:
            normalized[cleaned_key] = cleaned_values
    return normalized


def _source_fingerprint(
    chunks: Sequence[RawChunkRecord],
    source_version_ids: Sequence[str],
    seed_terms: Mapping[str, Sequence[str]],
) -> str:
    payload = {
        "source_version_ids": sorted(set(source_version_ids)),
        "chunks": sorted((chunk.id, chunk.content_sha256) for chunk in chunks),
        "seed_terms": {
            key: list(values)
            for key, values in sorted(seed_terms.items(), key=lambda item: item[0])
        },
    }
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return sha256(canonical.encode("utf-8")).hexdigest()


def _read_cached_terms(
    path: Path,
    source_version_ids: Sequence[str],
    source_fingerprint: str,
) -> dict[str, tuple[str, ...]] | None:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    if payload.get("schema_version") != _SCHEMA_VERSION:
        return None
    if payload.get("source_version_ids") != sorted(set(source_version_ids)):
        return None
    if payload.get("source_fingerprint") != source_fingerprint:
        return None
    raw_terms = payload.get("terms")
    if not isinstance(raw_terms, dict):
        return None
    normalized: dict[str, tuple[str, ...]] = {}
    for key, values in raw_terms.items():
        if not isinstance(key, str) or not isinstance(values, list) or any(
            not isinstance(value, str) for value in values
        ):
            return None
        normalized[key] = tuple(values)
    return normalized


__all__ = [
    "DEFAULT_SEED_TERMS",
    "build_bilingual_dictionary",
    "expand_query",
    "load_or_build_dictionary",
    "tokenize_query",
]
