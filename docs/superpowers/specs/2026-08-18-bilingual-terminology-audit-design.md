# Bilingual Terminology Audit Design

## Goal

Make the local Chinese-English retrieval glossary high precision across the CACA, CSCO, and NCCN source chunks, eliminating OCR-derived false mappings such as `mmol/L` to `高危` while preserving verified oncology terminology.

## Scope

- Audit all mappings currently generated in `data/retrieval/bilingual_terms.json` and regenerate the runtime glossary from the three searchable guideline versions.
- Tighten automatic extraction in `app/terminology.py` so units, doses, numeric thresholds, identifiers, URLs, statistical fragments, and sentence fragments cannot become aliases.
- Add a small verified seed glossary for clinically important concepts that are missing or too generic, including lymph-node metastasis and high-risk terminology.
- Add regression tests and a human-readable audit report of retained, rejected, and manually corrected mappings.
- Do not change source JSONL, vector embeddings, or vector index files. The glossary is applied at query time; restarting the API is sufficient after regeneration.

## Design

### 1. Candidate extraction

Parenthesized bilingual candidates remain the discovery mechanism, but a candidate is accepted only when:

- one side is a substantive Chinese clinical term and the other side is a plausible English full term or established abbreviation;
- the English side is not a measurement unit, dose, percentage, URL, identifier, trial code, statistical expression, or comparison fragment;
- neither side is a sentence fragment, clause, author attribution, table label, or OCR residue;
- the pair passes reciprocal normalization and language-shape checks.

Candidates that cannot be proven equivalent are excluded from the retrieval glossary, even if they remain present in the source OCR.

### 2. Verified seeds

Seed terms provide stable high-value retrieval expansion and are reviewed separately from OCR extraction. They include:

- `淋巴转移` -> `lymph node metastasis`, `nodal metastasis`;
- `高危` -> `high risk`, `high-risk`;
- existing core disease, treatment, subtype, drug, and guideline terms already present in `DEFAULT_SEED_TERMS`.

The seed list is subject to the same normalization and duplicate checks as extracted terms.

### 3. Audit output

The rebuild writes the normal runtime glossary and a deterministic audit report under `data/retrieval/`. The report records source versions, counts, rejected candidates with reasons, and manually seeded mappings. It is diagnostic data, not an additional index input.

### 4. Runtime behavior

`expand_query()` continues to preserve the original query and append only aliases from the cleaned glossary. For a query such as `淋巴转移 高危`, the expected expansion contains the original Chinese terms and their verified English equivalents, and must not contain `mmol/L`, dose units, or unrelated sentence fragments.

## Verification

- Unit tests fail before the extractor changes for the `mmol/L（高危）` and sentence-fragment cases.
- Unit tests pass after the changes for rejection, reciprocal aliases, verified seed terms, and multi-keyword expansion.
- A full rebuild scans all three guideline source sets and reports zero rejected unit/identifier aliases in the final glossary.
- A deterministic audit script checks every final mapping for accepted language shape, forbidden patterns, and reciprocal consistency.
- Representative expansions are checked for `淋巴转移 高危`, `复发转移 疗法`, `ADC`, and known drug names.

## Operational Note

After the glossary is regenerated, restart the API process on port 8001. No BGE model download and no vector re-embedding are required for this change.
