from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import zipfile


INCLUDED_ROOTS = (
    "registry",
    "llama_indices",
    "managed_sources",
    "reports",
    "staging",
)
EXCLUDED_ROOTS = ("model_cache", "runtime_cache", "vendor_wheels")
FORBIDDEN_SUFFIXES = (".wal", ".shm", ".tmp")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _collect_files(data_root: Path, stage_data_root: Path) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    for root_name in INCLUDED_ROOTS:
        source_root = data_root / root_name
        if not source_root.is_dir():
            raise FileNotFoundError(f"required data directory is missing: {source_root}")
        destination_root = stage_data_root / root_name
        for source_path in sorted(source_root.rglob("*")):
            if not source_path.is_file():
                continue
            if source_path.suffix.lower() in FORBIDDEN_SUFFIXES:
                raise ValueError(f"temporary SQLite/runtime file is not allowed: {source_path}")
            relative = source_path.relative_to(data_root)
            destination = stage_data_root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source_path, destination)
            records.append(
                {
                    "path": (Path("data") / relative).as_posix(),
                    "size": destination.stat().st_size,
                    "sha256": _sha256(destination),
                }
            )
    return records


def _write_manifest(stage_data_root: Path, version: str, files: list[dict[str, object]]) -> Path:
    manifest = {
        "format": "breast-knowledgebase-data",
        "version": version,
        "included_roots": [f"data/{root}" for root in INCLUDED_ROOTS],
        "excluded_roots": [f"data/{root}" for root in EXCLUDED_ROOTS],
        "files": sorted(files, key=lambda item: str(item["path"])),
    }
    path = stage_data_root / "DATA_MANIFEST.json"
    path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return path


def _write_zip(stage_root: Path, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(
        output_path,
        mode="w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=9,
    ) as archive:
        for source_path in sorted(stage_root.rglob("*")):
            if not source_path.is_file():
                continue
            relative = source_path.relative_to(stage_root).as_posix()
            info = zipfile.ZipInfo(relative, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 0
            info.external_attr = 0
            archive.writestr(info, source_path.read_bytes())


def build_bundle(*, project_root: Path, output_dir: Path, version: str) -> tuple[Path, Path]:
    data_root = (project_root / "data").resolve()
    if not data_root.is_dir():
        raise FileNotFoundError(data_root)
    output_dir = output_dir.resolve()
    stem = f"breast-knowledgebase-data-{version}"
    archive_path = output_dir / f"{stem}.zip"
    checksum_path = output_dir / f"{stem}.zip.sha256"
    with tempfile.TemporaryDirectory(prefix="data-release-", dir=output_dir) as temporary:
        stage_root = Path(temporary)
        stage_data_root = stage_root / "data"
        stage_data_root.mkdir()
        files = _collect_files(data_root, stage_data_root)
        _write_manifest(stage_data_root, version, files)
        _write_zip(stage_root, archive_path)
    checksum_path.write_text(
        f"{_sha256(archive_path)}  {archive_path.name}\n",
        encoding="ascii",
        newline="\n",
    )
    return archive_path, checksum_path


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build the vectorized knowledgebase data package without model caches."
    )
    parser.add_argument("--project-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--version", default="v0.2.0-internal-test")
    arguments = parser.parse_args()
    project_root = arguments.project_root.resolve()
    output_dir = (arguments.output_dir or project_root / "dist").resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    archive_path, checksum_path = build_bundle(
        project_root=project_root,
        output_dir=output_dir,
        version=arguments.version,
    )
    print(f"archive={archive_path}")
    print(f"archive_bytes={archive_path.stat().st_size}")
    print(f"checksum={checksum_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
