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
    "脑转移": ("brain metastasis", "cerebral metastasis"),
    "淋巴转移": ("lymph node metastasis", "nodal metastasis"),
    "淋巴结转移": ("lymph node metastasis", "nodal metastasis"),
    "高危": ("high risk", "high-risk"),
    "复发转移": ("recurrent metastatic", "recurrent or metastatic"),
    "复发转移性乳腺癌": ("recurrent metastatic breast cancer",),
    "晚期乳腺癌": ("advanced breast cancer",),
    "晚期": ("advanced", "advanced-stage"),
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
    "阿贝西利": ("abemaciclib",),
    "哌柏西利": ("palbociclib",),
    "瑞波西利": ("ribociclib",),
    "达尔西利": ("dalpiciclib",),
    "阿培利司": ("alpelisib",),
    "卡匹色替": ("capivasertib",),
    "依维莫司": ("everolimus",),
    "艾拉司群": ("elacestrant",),
    "他莫昔芬": ("tamoxifen", "TAM"),
    "雷洛昔芬": ("raloxifene",),
    "地舒单抗": ("denosumab",),
    "戈沙妥珠单抗": ("sacituzumab govitecan",),
    "优替德隆": ("utidelone", "UTD1"),
    "芦康沙妥珠单抗": ("sacituzumab tirumotecan", "SKB264"),
    "芳香化酶抑制剂": ("aromatase inhibitor", "AI"),
    "选择性雌激素受体调节剂": (
        "selective estrogen receptor modulator",
        "SERM",
    ),
    "选择性雌激素受体降解剂": (
        "selective estrogen receptor degrader",
        "SERD",
    ),
    "抗体药物偶联物": ("antibody-drug conjugate", "ADC"),
    "表观扩散系数": ("apparent diffusion coefficient", "ADC"),
    "卵巢功能抑制": ("ovarian function suppression", "OFS"),
    "免疫检查点抑制剂": ("immune checkpoint inhibitor", "ICI"),
    "中性粒细胞绝对计数": ("absolute neutrophil count", "ANC"),
    "发热性中性粒细胞减少症": ("febrile neutropenia", "FN"),
    "肿瘤相关性贫血": ("cancer-related anemia", "CRA"),
    "红细胞生成刺激剂": ("erythropoiesis-stimulating agent", "ESA"),
    "促红细胞生成素": ("erythropoietin", "EPO"),
    "化疗所致恶心呕吐": ("chemotherapy-induced nausea and vomiting", "CINV"),
    "化疗所致血小板减少症": ("chemotherapy-induced thrombocytopenia", "CIT"),
    "粒细胞集落刺激因子": ("granulocyte colony-stimulating factor", "G-CSF"),
    "免疫组织化学": ("immunohistochemistry", "IHC"),
    "原位杂交": ("in situ hybridization", "ISH"),
    "淋巴血管侵犯": ("lymphovascular invasion", "LVI"),
    "无浸润性疾病生存期": ("invasive disease-free survival", "iDFS"),
    "病理学完全缓解": ("pathologic complete response", "pCR"),
    "残余肿瘤负荷": ("residual cancer burden", "RCB"),
    "前哨淋巴结活检": ("sentinel lymph node biopsy", "SLNB"),
    "腋窝淋巴结清扫术": ("axillary lymph node dissection", "ALND"),
    "导管原位癌": ("ductal carcinoma in situ", "DCIS"),
    "转移性三阴性乳腺癌": ("metastatic triple-negative breast cancer", "mTNBC"),
    "人表皮生长因子受体2": ("human epidermal growth factor receptor 2", "HER2"),
    "雌激素受体": ("estrogen receptor", "ER"),
    "孕激素受体": ("progesterone receptor", "PR"),
    "阳性预测值": ("positive predictive value", "PPV"),
    "体重指数": ("body mass index", "BMI"),
    "左心室射血分数": ("left ventricular ejection fraction", "LVEF"),
    "抗肿瘤治疗相关心功能不全": (
        "cancer treatment-related cardiac dysfunction",
        "CTRCD",
    ),
    "间质性肺病": ("interstitial lung disease", "ILD"),
    "骨相关事件": ("skeletal-related event", "SRE"),
    "肿瘤突变负荷": ("tumor mutation burden", "TMB"),
    "肿瘤浸润淋巴细胞": ("tumor-infiltrating lymphocytes", "TILs"),
    "二代测序": ("next-generation sequencing", "NGS"),
    "真实世界研究": ("real-world study", "RWS"),
    "机会性筛查": ("opportunistic screening",),
    "部分乳腺照射": ("partial breast irradiation", "PBI"),
    "加速部分乳腺照射": ("accelerated partial breast irradiation", "APBI"),
    "适形调强放疗": ("intensity-modulated radiation therapy", "IMRT"),
    "容积旋转调强放疗": ("volumetric modulated arc therapy", "VMAT"),
    "立体定向放射外科": ("stereotactic radiosurgery", "SRS"),
    "磁共振成像": ("magnetic resonance imaging", "MRI"),
    "最大信号投影": ("maximum intensity projection", "MIP"),
    "感兴趣区": ("region of interest", "ROI"),
    "低密度脂蛋白胆固醇": ("low-density lipoprotein cholesterol", "LDL-C"),
    "美国国家综合癌症网络": ("National Comprehensive Cancer Network", "NCCN"),
    "中国临床肿瘤学会": ("Chinese Society of Clinical Oncology", "CSCO"),
    "中国抗癌协会": ("Chinese Anti-Cancer Association", "CACA"),
    "国际癌症研究机构": ("International Agency for Research on Cancer", "IARC"),
    "美国癌症联合委员会": ("American Joint Committee on Cancer", "AJCC"),
    "美国临床肿瘤学会": ("American Society of Clinical Oncology", "ASCO"),
    "欧洲肿瘤内科学会": ("European Society for Medical Oncology", "ESMO"),
    "世界卫生组织": ("World Health Organization", "WHO"),
    "不良反应": ("adverse events", "toxicity"),
    "疗效": ("efficacy",),
    "剂量": ("dose", "dosing"),
    "风险": ("risk",),
    "Van Nuys预后指数": ("van Nuys prognostic index", "VNPI"),
}

# These pairs were reviewed against the local guideline wording. Automatically
# discovered candidates outside this allowlist are retained only in the audit
# report and never enter the runtime query expansion glossary.
REVIEWED_EXTRACTED_TERMS: dict[str, tuple[str, ...]] = {
    "阿贝西利": ("abemaciclib",),
    "部分乳腺短程照射": ("accelerated partial breast irradiation",),
    "抗肿瘤治疗所致药物性肝损伤": (
        "anti-neoplastic treatment-induced liver injury",
    ),
    "抗体药物偶联物": ("antibody-drug conjugates", "ADC"),
    "表观扩散系数": ("apparent diffusion coefficient", "ADC"),
    "部分乳腺照射": ("partial breast irradiation",),
    "芳香化酶抑制剂": ("aromatase inhibitor",),
    "天冬氨酸转氨酶": ("aspartate aminotransferase",),
    "贝克抑郁自评量表": ("BDI",),
    "乳腺癌治疗结局测评": ("breast cancer treatment outcome scale",),
    "乳腺癌": ("breast cancer",),
    "抗肿瘤治疗相关心功能不全": (
        "cancer treatment-related cardiac dysfunction",
    ),
    "心脏磁共振成像": ("cardiac magnetic resonance",),
    "化疗": ("chemotherapy",),
    "慢性阻塞性肺疾病": ("COPD",),
    "卡培他滨": ("capecitabine",),
    "达尔西利": ("dalpiciclib",),
    "腹壁下深血管穿支皮瓣": (
        "deep inferior epigastric artery perforator flap",
    ),
    "无病间期": ("disease-free interval",),
    "多西他赛": ("docetaxel",),
    "剂量": ("dose",),
    "疗效": ("efficacy",),
    "内分泌治疗": ("endocrine therapy",),
    "艾拉司群": ("elacestrant",),
    "发热性中性粒细胞减少症": ("febrile neutropenia",),
    "游离横型腹直肌肌皮瓣": (
        "free transverse rectus abdominis musculocutaneous flap",
    ),
    "广泛性焦虑障碍问卷": ("GAD-7",),
    "促性腺激素释放激素类似物": (
        "gonadotropin-releasing hormone analogue",
    ),
    "粒细胞集落刺激因子": ("granulocyte colony stimulating factor",),
    "HER2阳性": ("HER2-positive",),
    "激素受体阳性": ("hormone receptor-positive",),
    "国际癌症研究机构": ("International Agency for Research on Cancer",),
    "免疫治疗": ("immunotherapy",),
    "适形调强放疗": ("intensity-modulated radiation therapy",),
    "失眠严重程度指数量表": ("ISI",),
    "孤立肿瘤细胞": ("isolated tumor cells",),
    "拉帕替尼": ("lapatinib",),
    "外内侧": ("lateromedial",),
    "外侧头足": ("lateral craniocaudal",),
    "低密度脂蛋白胆固醇": ("low density lipoprotein-cholesterol",),
    "局部复发": ("local recurrence",),
    "左心室射血分数": ("left ventricular ejection fraction",),
    "淋巴管血管侵犯": ("lymphovascular invasion",),
    "哺乳动物雷帕霉素靶蛋白": ("mammalian target of rapamycin",),
    "最大信号投影": ("maximum intensity projection",),
    "内外侧": ("mediolateral",),
    "内侧头足": ("medial craniocaudal",),
    "转移性三阴性乳腺癌": ("mTNBC",),
    "转移": ("metastasis",),
    "转移性乳腺癌": ("metastatic breast cancer",),
    "复发": ("recurrence", "recurrent"),
    "复发转移": ("recurrent metastatic", "recurrent or metastatic"),
    "复发转移性乳腺癌": ("recurrent metastatic breast cancer",),
    "乳腺肿瘤整形手术": ("oncoplastic surgery",),
    "哌柏西利": ("palbociclib",),
    "紫杉醇": ("paclitaxel",),
    "病理学完全缓解": ("pathologic complete response",),
    "部分缓解": ("partial response",),
    "经外周静脉穿刺置管": ("peripherally inserted central catheter",),
    "帕妥珠单抗": ("pertuzumab",),
    "磷脂酰肌醇3-激酶": ("phosphoinositide 3-kinase",),
    "乳腺叶状肿瘤": ("phyllodes tumor",),
    "孕激素受体": ("progesterone receptor",),
    "蛋白水解靶向嵌合体": ("PROTAC",),
    "吡咯替尼": ("pyrotinib",),
    "垂直切缘放射状取材": ("radial sections perpendicular to the margin",),
    "放疗": ("radiation therapy", "radiotherapy"),
    "雷洛昔芬": ("raloxifene",),
    "受体活化因子配体": ("receptor activator of NF-κB ligand",),
    "残余肿瘤负荷": ("residual cancer burden",),
    "真实世界研究": ("real world study",),
    "戈沙妥珠单抗": ("sacituzumab govitecan",),
    "焦虑自评量表": ("SAS",),
    "前哨淋巴结活检": ("sentinel lymph node biopsy",),
    "选择性雌激素受体调节剂": ("selective estrogen receptor modulator",),
    "臀上动脉穿支皮瓣": ("superior gluteal artery perforator flap",),
    "骨相关事件": ("skeletal-related event",),
    "脊柱不稳定肿瘤学评分": ("SINS",),
    "立体定向放射外科治疗": ("stereotactic radiosurgery",),
    "疾病稳定": ("stable disease",),
    "三阴性乳腺癌": ("triple-negative breast cancer",),
    "恩美曲妥珠单抗": ("T-DM1",),
    "德曲妥珠单抗": ("T-DXd",),
    "他莫昔芬": ("tamoxifen",),
    "靶向治疗": ("targeted therapy",),
    "三级淋巴结构": ("tertiary lymphoid structures",),
    "治疗": ("therapy", "treatment"),
    "横型股薄肌肌皮瓣": ("transverse myocutaneous gracilis flap",),
    "带蒂横型腹直肌肌皮瓣": (
        "transverse rectus abdominis musculocutaneous flap",
    ),
    "曲妥珠单抗": ("trastuzumab",),
    "促甲状腺素": ("TSH",),
    "肿瘤浸润淋巴细胞": ("tumor-infiltrating lymphocytes",),
    "肿瘤突变负荷": ("tumor mutation burden",),
    "优替德隆": ("UTD1",),
    "Van Nuys预后指数": ("van Nuys prognostic index", "VNPI"),
    "世界卫生组织": ("World Health Organization",),
    "中国年轻乳腺癌": ("Young Breast Cancer in China",),
}

_SCHEMA_VERSION = 3
_ASCII_TOKEN = re.compile(r"[A-Za-z0-9]+(?:[./+_-][A-Za-z0-9]+)*")
_AMBIGUOUS_ASCII_ALIAS_PATTERN = re.compile(
    r"[A-Z0-9][A-Z0-9-]{1,3}", re.IGNORECASE
)
_QUERY_STOPWORDS = frozenset(
    {
        "and",
        "or",
        "with",
        "without",
        "of",
        "the",
        "a",
        "an",
        "in",
        "for",
        "to",
        "on",
    }
)
_QUERY_GROUP_CONNECTORS = frozenset({"and", "or", "with", "without"})
_QUERY_GROUP_PUNCTUATION = "，,;；。:："
_CHINESE_RUN = re.compile(r"[\u3400-\u9fff]+")
_MEASUREMENT_UNIT = re.compile(
    r"(?i)^(?:mmol|mol|mg|mcg|ug|g|kg|ml|l|cm|mm|hz|khz|mhz)"
    r"(?:/[a-z]+)?(?:\^?[23]|[\u00b2\u00b3])?$"
)
_IDENTIFIER = re.compile(r"(?i)(?:^|\b)(?:orcid|nct\d+|www\.|https?://)")
_COMPARISON_OR_DOSE = re.compile(
    r"[<>=\u2264\u2265%]|\d+(?:\.\d+)?\s*"
    r"(?:mmol|mol|mg|mcg|ug|g|kg|ml|l|cm|mm)(?:/[a-z]+)?",
    re.IGNORECASE,
)
_CLAUSE_PREFIXES = (
    "如果",
    "依据",
    "同时",
    "包括",
    "其中",
    "对于",
    "通过",
    "建议",
    "推荐",
    "必要时",
    "目前",
    "主要",
    "和",
    "及",
    "或",
    "如",
    "由",
)
_CONTEXT_MARKERS = (
    "包括",
    "参考",
    "参照",
    "建议",
    "推荐",
    "考虑",
    "此外",
    "其次",
    "一般",
    "依据",
    "同时",
    "目前",
    "需要",
    "结果按照",
    "可显著",
    "可选择",
    "须在",
    "本指南",
)
_GENERIC_CHINESE_LABELS = frozenset(
    {
        "个月",
        "分期",
        "推荐",
        "可选",
        "阳性",
        "阴性",
        "风险",
        "治疗",
        "抑制剂",
        "患者",
    }
)
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
    """Append aliases for longest, non-overlapping local query terms."""
    original = " ".join(query.strip().split())
    if not original:
        return original

    expanded: list[str] = [original]
    seen = {original.casefold()}
    lowered = original.casefold()
    matches = _select_query_term_matches(original, terms, lowered)
    for key, _, _ in matches:
        for alias in terms[key]:
            cleaned = " ".join(str(alias).split())
            if not cleaned or cleaned.casefold() in seen:
                continue
            expanded.append(cleaned)
            seen.add(cleaned.casefold())
    return " ".join(expanded)


def query_concept_groups(
    query: str,
    terms: Mapping[str, Sequence[str]],
) -> tuple[tuple[str, ...], ...]:
    """Return matched bilingual concept groups for strict multi-keyword search."""
    original = " ".join(query.strip().split())
    if not original:
        return ()
    groups_with_spans: list[tuple[int, tuple[str, ...]]] = []
    matches = _select_query_term_matches(original, terms, original.casefold())
    covered_spans = [(start, end) for _, start, end in matches]
    for key, start, _ in matches:
        variants = [key, *terms.get(key, ())]
        if key == "淋巴转移":
            variants.extend(
                (
                    "淋巴结转移",
                    "腋窝淋巴结转移",
                    "区域淋巴结转移",
                    "淋巴结阳性",
                    "腋窝淋巴结阳性",
                )
            )
        cleaned = tuple(
            dict.fromkeys(
                " ".join(str(value).split())
                for value in variants
                if str(value).strip()
            )
        )
        if cleaned:
            groups_with_spans.append((start, cleaned))

    # Unrecognized Chinese tokens remain separate concepts. Consecutive ASCII
    # tokens form one phrase because whitespace is part of normal English text.
    ascii_phrase: list[str] = []
    ascii_phrase_start: int | None = None

    def flush_ascii_phrase() -> None:
        nonlocal ascii_phrase_start
        if ascii_phrase and ascii_phrase_start is not None:
            groups_with_spans.append((ascii_phrase_start, (" ".join(ascii_phrase),)))
        ascii_phrase.clear()
        ascii_phrase_start = None

    for token_match in re.finditer(r"\S+", original):
        if any(
            token_match.start() < end and start < token_match.end()
            for start, end in covered_spans
        ):
            flush_ascii_phrase()
            continue

        raw_token = token_match.group(0)
        has_leading_separator = raw_token[0] in _QUERY_GROUP_PUNCTUATION
        has_trailing_separator = raw_token[-1] in _QUERY_GROUP_PUNCTUATION
        if has_leading_separator:
            flush_ascii_phrase()
        token = raw_token.strip(_QUERY_GROUP_PUNCTUATION)
        lowered_token = token.casefold()

        if lowered_token in _QUERY_GROUP_CONNECTORS:
            flush_ascii_phrase()
            continue
        if _CHINESE_RUN.search(token):
            flush_ascii_phrase()
            if len(token) >= 2:
                groups_with_spans.append((token_match.start(), (token,)))
        elif _ASCII_TOKEN.fullmatch(token) and lowered_token not in _QUERY_STOPWORDS:
            if ascii_phrase_start is None:
                ascii_phrase_start = token_match.start()
            ascii_phrase.append(token)
        elif _ASCII_TOKEN.fullmatch(token) and ascii_phrase:
            ascii_phrase.append(token)
        else:
            flush_ascii_phrase()

        if has_trailing_separator:
            flush_ascii_phrase()

    flush_ascii_phrase()

    return tuple(
        group for _, group in sorted(groups_with_spans, key=lambda item: item[0])
    )


def _select_query_term_matches(
    original: str,
    terms: Mapping[str, Sequence[str]],
    lowered: str,
) -> list[tuple[str, int, int]]:
    candidates: list[tuple[str, int, int]] = []
    for key in terms:
        if not key.strip() or _is_ambiguous_ascii_alias(key, terms):
            continue
        for start, end in _query_term_spans(original, key, lowered):
            candidates.append((key, start, end))

    selected: list[tuple[str, int, int]] = []
    for key, start, end in sorted(
        candidates,
        key=lambda item: (-(item[2] - item[1]), item[1], item[0].casefold(), item[0]),
    ):
        if any(
            start < selected_end and selected_start < end
            for _, selected_start, selected_end in selected
        ):
            continue
        selected.append((key, start, end))
    return sorted(
        selected,
        key=lambda item: (item[1], -(item[2] - item[1]), item[0].casefold()),
    )


def _query_term_spans(
    original: str,
    key: str,
    lowered: str,
) -> list[tuple[int, int]]:
    normalized_key = key.casefold()
    if _CHINESE_RUN.search(key):
        return [
            (match.start(), match.end())
            for match in re.finditer(re.escape(normalized_key), lowered)
        ]
    if not normalized_key:
        return []
    pattern = rf"(?<![A-Za-z0-9]){re.escape(normalized_key)}(?![A-Za-z0-9])"
    return [
        (match.start(), match.end())
        for match in re.finditer(pattern, lowered)
    ]


def _is_ambiguous_ascii_alias(key: str, terms: Mapping[str, Sequence[str]]) -> bool:
    if _CHINESE_RUN.search(key) or _AMBIGUOUS_ASCII_ALIAS_PATTERN.fullmatch(key) is None:
        return False
    chinese_targets = {
        target
        for target in terms.get(key, ())
        if isinstance(target, str) and _CHINESE_RUN.search(target)
    }
    return len(chinese_targets) > 1


def build_bilingual_dictionary(
    chunks: Iterable[RawChunkRecord],
    seed_terms: Mapping[str, Sequence[str]] | None = None,
) -> dict[str, tuple[str, ...]]:
    """Build a deterministic bidirectional glossary from local source text."""
    terms, _ = _build_bilingual_dictionary_with_audit(chunks, seed_terms)
    return terms


def _build_bilingual_dictionary_with_audit(
    chunks: Iterable[RawChunkRecord],
    seed_terms: Mapping[str, Sequence[str]] | None = None,
) -> tuple[dict[str, tuple[str, ...]], dict[str, object]]:
    aliases: dict[str, set[str]] = {}
    normalized_seeds = _normalize_terms(seed_terms or {})
    _validate_seed_terms(normalized_seeds)
    reviewed_terms = _normalize_terms({**REVIEWED_EXTRACTED_TERMS, **normalized_seeds})
    reviewed_pairs = {
        (english.casefold(), chinese)
        for chinese, values in reviewed_terms.items()
        for english in values
    }
    rejected: list[dict[str, str]] = []
    automatic_candidates: list[tuple[RawChunkRecord, str, str]] = []

    for source, values in normalized_seeds.items():
        for value in values:
            _add_alias(aliases, source, value)

    for chunk in chunks:
        text = chunk.text
        for match in _ZH_PAREN.finditer(text):
            chinese = _clean_term(match.group("zh"))
            for alias in _split_alias_candidates(match.group("inside")):
                reason = _candidate_rejection_reason(alias, chinese)
                if reason is None and (alias.casefold(), chinese) not in reviewed_pairs:
                    reason = "unreviewed_candidate"
                if reason is not None:
                    rejected.append(_rejected_candidate(chunk, alias, chinese, reason))
                    continue
                automatic_candidates.append((chunk, alias, chinese))
        for match in _EN_PAREN.finditer(text):
            english = _clean_term(match.group("en"))
            chinese = _clean_term(match.group("zh"))
            reason = _candidate_rejection_reason(english, chinese)
            if reason is None and (english.casefold(), chinese) not in reviewed_pairs:
                reason = "unreviewed_candidate"
            if reason is not None:
                rejected.append(_rejected_candidate(chunk, english, chinese, reason))
                continue
            automatic_candidates.append((chunk, english, chinese))

    targets_by_english: dict[str, set[str]] = {}
    for _, english, chinese in automatic_candidates:
        targets_by_english.setdefault(english.casefold(), set()).add(chinese)
    for chunk, english, chinese in automatic_candidates:
        if len(targets_by_english[english.casefold()]) > 1:
            rejected.append(
                _rejected_candidate(chunk, english, chinese, "ambiguous_alias")
            )
            continue
        _add_alias(aliases, english, chinese)

    terms = {
        key: tuple(sorted(values, key=lambda value: (value.casefold(), value)))
        for key, values in sorted(aliases.items(), key=lambda item: (item[0].casefold(), item[0]))
        if values
    }
    audit_errors = audit_bilingual_dictionary(terms)
    if audit_errors:
        raise ValueError("invalid bilingual dictionary: " + "; ".join(audit_errors))
    unique_rejected = {
        (item["chunk_id"], item["source"], item["target"], item["reason"]): item
        for item in rejected
    }
    rejected_candidates = [
        unique_rejected[key]
        for key in sorted(
            unique_rejected,
            key=lambda item: (item[0], item[1].casefold(), item[2].casefold(), item[3]),
        )
    ]
    audit = {
        "accepted_pair_count": _unique_pair_count(terms),
        "rejected_candidate_count": len(rejected_candidates),
        "rejected_candidates": rejected_candidates,
        "reviewed_seeds": {
            key: list(values)
            for key, values in sorted(
                normalized_seeds.items(), key=lambda item: (item[0].casefold(), item[0])
            )
        },
    }
    return terms, audit


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

    audit_destination = _audit_path(destination)
    cached = _read_cached_terms(destination, source_version_ids, source_fingerprint)
    if cached is not None and _read_cached_audit(
        audit_destination, source_version_ids, source_fingerprint, cached
    ):
        return cached

    terms, audit = _build_bilingual_dictionary_with_audit(materialized, normalized_seeds)
    payload = {
        "schema_version": _SCHEMA_VERSION,
        "source_version_ids": sorted(set(source_version_ids)),
        "source_fingerprint": source_fingerprint,
        "term_count": len(terms),
        "terms": {key: list(values) for key, values in terms.items()},
    }
    audit_payload = {
        "schema_version": _SCHEMA_VERSION,
        "source_version_ids": sorted(set(source_version_ids)),
        "source_fingerprint": source_fingerprint,
        **audit,
    }
    audit_payload["audit_digest"] = _payload_digest(audit_payload)
    destination.parent.mkdir(parents=True, exist_ok=True)
    _write_json_atomic(destination, payload)
    _write_json_atomic(audit_destination, audit_payload)
    return terms


def _add_alias(aliases: dict[str, set[str]], source: str, target: str) -> None:
    source = _clean_term(source)
    target = _clean_term(target)
    if not source or not target or source.casefold() == target.casefold():
        return
    aliases.setdefault(source, set()).add(target)
    aliases.setdefault(target, set()).add(source)


def _split_alias_candidates(value: str) -> list[str]:
    pieces = re.split(r"[，,;；]", value)
    return [
        cleaned
        for piece in pieces
        if (cleaned := _clean_term(piece))
    ]


def _clean_term(value: str) -> str:
    return " ".join(value.strip(" \t\r\n:：;；,，") .split())


def _is_english_alias(value: str) -> bool:
    return _english_rejection_reason(value) is None


def _is_chinese_term(value: str) -> bool:
    return _chinese_rejection_reason(value) is None


def _candidate_rejection_reason(english: str, chinese: str) -> str | None:
    return _english_rejection_reason(english) or _chinese_rejection_reason(chinese)


def _validate_seed_terms(seed_terms: Mapping[str, Sequence[str]]) -> None:
    trusted_pairs = _trusted_reviewed_pairs()
    for chinese, values in seed_terms.items():
        for english in values:
            pair = (english.casefold(), chinese)
            reason = (
                _trusted_seed_rejection_reason(english, chinese)
                if pair in trusted_pairs
                else _candidate_rejection_reason(english, chinese)
            )
            if reason is not None:
                raise ValueError(
                    f"invalid seed mapping ({reason}): {chinese!r} -> {english!r}"
                )


def _trusted_seed_rejection_reason(english: str, chinese: str) -> str | None:
    if _IDENTIFIER.search(english) or _MEASUREMENT_UNIT.fullmatch(english):
        return "measurement_or_threshold" if _MEASUREMENT_UNIT.fullmatch(english) else "identifier"
    if _COMPARISON_OR_DOSE.search(english) or not re.match(r"^[A-Za-z]", english):
        return "measurement_or_threshold" if _COMPARISON_OR_DOSE.search(english) else "invalid_term_shape"
    if any("\u3400" <= character <= "\u9fff" for character in english):
        return "invalid_term_shape"
    if any(marker in chinese for marker in _CONTEXT_MARKERS) or chinese.endswith("患者"):
        return "sentence_fragment"
    if not 2 <= len(chinese) <= 24 or re.search(r"[，。；：,.;:（）()]", chinese):
        return "invalid_term_shape"
    if not _CHINESE_RUN.search(chinese):
        return "invalid_term_shape"
    return None


def _trusted_reviewed_pairs() -> set[tuple[str, str]]:
    pairs: set[tuple[str, str]] = set()
    for glossary in (DEFAULT_SEED_TERMS, REVIEWED_EXTRACTED_TERMS):
        normalized = _normalize_terms(glossary)
        pairs.update(
            (english.casefold(), chinese)
            for chinese, values in normalized.items()
            for english in values
        )
    return pairs


def _english_rejection_reason(value: str) -> str | None:
    if _IDENTIFIER.search(value):
        return "identifier"
    if _MEASUREMENT_UNIT.fullmatch(value) or _COMPARISON_OR_DOSE.search(value):
        return "measurement_or_threshold"
    if len(value) > 80 or not re.match(r"^[A-Za-z]", value):
        return "invalid_term_shape"
    if len(re.findall(r"[A-Za-z]", value)) < 3:
        return "invalid_term_shape"
    if any("\u3400" <= character <= "\u9fff" for character in value):
        return "invalid_term_shape"
    return None


def _chinese_rejection_reason(value: str) -> str | None:
    if value in _GENERIC_CHINESE_LABELS or value.startswith(_CLAUSE_PREFIXES):
        return "sentence_fragment"
    if any(marker in value for marker in _CONTEXT_MARKERS) or value.endswith("患者"):
        return "sentence_fragment"
    if not 2 <= len(value) <= 16:
        return "invalid_term_shape"
    if re.search(r"[，。；：,.;:（）()]", value):
        return "invalid_term_shape"
    if re.search(r"[A-Za-z]", value):
        return "invalid_term_shape"
    if not re.search(r"[\u3400-\u9fff]", value):
        return "invalid_term_shape"
    return None


def _rejected_candidate(
    chunk: RawChunkRecord,
    source: str,
    target: str,
    reason: str,
) -> dict[str, str]:
    return {
        "chunk_id": chunk.chunk_id,
        "source": source,
        "target": target,
        "reason": reason,
    }


def _unique_pair_count(terms: Mapping[str, Sequence[str]]) -> int:
    pairs = {
        tuple(sorted((source, target), key=lambda value: (value.casefold(), value)))
        for source, values in terms.items()
        for target in values
    }
    return len(pairs)


def audit_bilingual_dictionary(terms: Mapping[str, Sequence[str]]) -> tuple[str, ...]:
    """Return deterministic quality errors for a runtime glossary."""
    errors: set[str] = set()
    trusted_pairs = _trusted_reviewed_pairs()
    for source, values in terms.items():
        if not isinstance(source, str):
            errors.add(f"invalid term key type: {source!r}")
            continue
        if not source.strip():
            errors.add("invalid empty term key")
            continue
        if not isinstance(values, (list, tuple)):
            errors.add(f"invalid term values: {source!r} must be a list of strings")
            continue
        if not values:
            errors.add(f"invalid empty term values: {source!r}")
            continue
        for target in values:
            if not isinstance(target, str):
                errors.add(f"invalid term value type: {source!r} -> {target!r}")
                continue
            source_has_chinese = bool(_CHINESE_RUN.search(source))
            target_has_chinese = bool(_CHINESE_RUN.search(target))
            if source.casefold() == target.casefold():
                errors.add(f"invalid mapping: {source!r} -> {target!r}")
                continue
            if source_has_chinese == target_has_chinese:
                errors.add(f"language-shape: {source!r} -> {target!r}")
                continue
            english = target if source_has_chinese else source
            chinese = source if source_has_chinese else target
            english_reason = _final_english_rejection_reason(english)
            chinese_reason = (
                None
                if (english.casefold(), chinese) in trusted_pairs
                else _chinese_rejection_reason(chinese)
            )
            if english_reason is not None or chinese_reason is not None:
                errors.add(
                    f"forbidden mapping ({english_reason or chinese_reason}): "
                    f"{source!r} -> {target!r}"
                )
            if source.casefold() not in {
                str(item).casefold() for item in terms.get(target, ())
            }:
                errors.add(f"non-reciprocal: {source!r} -> {target!r}")
    return tuple(sorted(errors))


def _final_english_rejection_reason(value: str) -> str | None:
    if _IDENTIFIER.search(value):
        return "identifier"
    if _MEASUREMENT_UNIT.fullmatch(value) or _COMPARISON_OR_DOSE.search(value):
        return "measurement_or_threshold"
    if len(value) > 80 or not re.match(r"^[A-Za-z]", value):
        return "invalid_term_shape"
    if any("\u3400" <= character <= "\u9fff" for character in value):
        return "invalid_term_shape"
    return None


def _audit_path(destination: Path) -> Path:
    return destination.with_name(f"{destination.stem}.audit{destination.suffix}")


def _write_json_atomic(destination: Path, payload: Mapping[str, object]) -> None:
    temporary = destination.with_name(f".{destination.name}.{uuid4().hex}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    temporary.replace(destination)


def _payload_digest(payload: Mapping[str, object]) -> str:
    canonical = json.dumps(
        {key: value for key, value in payload.items() if key != "audit_digest"},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return sha256(canonical.encode("utf-8")).hexdigest()


def _normalize_terms(terms: Mapping[str, Sequence[str]]) -> dict[str, tuple[str, ...]]:
    normalized: dict[str, tuple[str, ...]] = {}
    for key, values in terms.items():
        if isinstance(values, (str, bytes)) or not isinstance(values, Sequence):
            raise ValueError(f"term values for {key!r} must be a sequence of strings")
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
        "reviewed_extracted_terms": {
            key: list(values)
            for key, values in sorted(
                _normalize_terms(REVIEWED_EXTRACTED_TERMS).items(),
                key=lambda item: item[0],
            )
        },
        "filter_policy": {
            "schema_version": _SCHEMA_VERSION,
            "measurement_unit": _MEASUREMENT_UNIT.pattern,
            "identifier": _IDENTIFIER.pattern,
            "comparison_or_dose": _COMPARISON_OR_DOSE.pattern,
            "clause_prefixes": _CLAUSE_PREFIXES,
            "context_markers": _CONTEXT_MARKERS,
            "generic_chinese_labels": sorted(_GENERIC_CHINESE_LABELS),
            "ambiguous_ascii_alias_pattern": _AMBIGUOUS_ASCII_ALIAS_PATTERN.pattern,
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
        if not key.strip() or not values or any(not value.strip() for value in values):
            return None
        normalized[key] = tuple(values)
    if payload.get("term_count") != len(normalized):
        return None
    return normalized


def _read_cached_audit(
    path: Path,
    source_version_ids: Sequence[str],
    source_fingerprint: str,
    terms: Mapping[str, Sequence[str]],
) -> bool:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, UnicodeDecodeError, json.JSONDecodeError):
        return False
    if not isinstance(payload, dict):
        return False
    if payload.get("schema_version") != _SCHEMA_VERSION:
        return False
    if payload.get("source_version_ids") != sorted(set(source_version_ids)):
        return False
    if payload.get("source_fingerprint") != source_fingerprint:
        return False
    if payload.get("audit_digest") != _payload_digest(payload):
        return False
    if payload.get("accepted_pair_count") != _unique_pair_count(terms):
        return False
    rejected = payload.get("rejected_candidates")
    if not isinstance(rejected, list):
        return False
    if payload.get("rejected_candidate_count") != len(rejected):
        return False
    for item in rejected:
        if not isinstance(item, dict):
            return False
        if any(
            not isinstance(item.get(key), str)
            for key in ("chunk_id", "source", "target", "reason")
        ):
            return False
    return not audit_bilingual_dictionary(terms)


__all__ = [
    "DEFAULT_SEED_TERMS",
    "REVIEWED_EXTRACTED_TERMS",
    "audit_bilingual_dictionary",
    "build_bilingual_dictionary",
    "expand_query",
    "query_concept_groups",
    "load_or_build_dictionary",
    "tokenize_query",
]
