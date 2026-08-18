from __future__ import annotations

from dataclasses import asdict
import json
from pathlib import Path
import os
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.contracts import SearchRequest
from app.retrieval import _docstore_nodes, is_indexable_node
from app.service import GuidelineService
from app.settings import Settings


REPORT_PATH = PROJECT_ROOT / "data" / "reports" / "retrieval-multilingual-r1.json"
QUERIES = (
    "复发转移",
    "复发转移 疗法",
    "trastuzumab deruxtecan",
    "recurrent metastatic disease",
)


def main() -> int:
    os.environ.setdefault("KB_MODEL_LOCAL_FILES_ONLY", "true")
    settings = Settings.from_env(PROJECT_ROOT)
    service = GuidelineService(settings)
    versions = [
        version
        for version in service.registry.list_searchable_versions()
        if version.guideline_id
        in {"caca-breast-cancer", "csco-breast-cancer", "nccn-breast-cancer"}
    ]

    node_counts: dict[str, dict[str, int]] = {}
    cover_nodes_excluded = 0
    empty_nodes_excluded = 0
    for version in versions:
        index = service.index_store.load(service.snapshot_info(version.id))
        nodes = _docstore_nodes(index.docstore.docs.values())
        indexable_count = sum(is_indexable_node(node) for node in nodes)
        excluded = [node for node in nodes if not is_indexable_node(node)]
        empty = [
            node
            for node in excluded
            if not node.get_content(metadata_mode="none").strip()
        ]
        node_counts[version.id] = {
            "total": len(nodes),
            "indexable": indexable_count,
            "excluded": len(excluded),
        }
        cover_nodes_excluded += len(excluded) - len(empty)
        empty_nodes_excluded += len(empty)

    query_results = []
    for query in QUERIES:
        response = service.search(SearchRequest(query=query, top_k=3, use_bm25=True))
        payload = asdict(response)
        payload["guideline_ids"] = sorted(
            {item["guideline_id"] for item in payload["evidence"]}
        )
        query_results.append({"query": query, **payload})

    report = {
        "schema_version": 1,
        "source_versions": [
            {
                "id": version.id,
                "guideline_id": version.guideline_id,
                "version_label": version.version_label,
            }
            for version in versions
        ],
        "node_counts": node_counts,
        "cover_nodes_excluded": cover_nodes_excluded,
        "empty_nodes_excluded": empty_nodes_excluded,
        "queries": query_results,
        "glossary_path": str(settings.data_dir / "retrieval" / "bilingual_terms.json"),
    }
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = REPORT_PATH.with_name(f".{REPORT_PATH.name}.tmp")
    temporary.write_text(
        json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    temporary.replace(REPORT_PATH)
    print(REPORT_PATH)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
