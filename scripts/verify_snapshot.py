from __future__ import annotations

import argparse
from pathlib import Path

from app.index_store import SnapshotInfo
from app.service import GuidelineService
from app.settings import Settings


PROJECT_ROOT = Path(r"D:\coding\knowledgebase").resolve()


def verify_registered_snapshot(
    service: GuidelineService, version_id: str
) -> SnapshotInfo:
    snapshot = service.snapshot_info(version_id)
    service.index_store.verify(snapshot)
    service.index_store.load(snapshot)
    return snapshot


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Reopen and verify a registered LlamaIndex snapshot"
    )
    parser.add_argument("--version-id", required=True)
    arguments = parser.parse_args()
    service = GuidelineService(Settings.from_env(PROJECT_ROOT))
    snapshot = verify_registered_snapshot(service, arguments.version_id)
    print(f"verified {snapshot.version_id} {snapshot.manifest_sha256}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
