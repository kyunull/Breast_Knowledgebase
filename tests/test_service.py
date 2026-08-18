from __future__ import annotations

import tempfile
import gc
from contextlib import contextmanager
import os
from pathlib import Path

from llama_index.core.embeddings import MockEmbedding

from app.service import GuidelineService
from app.settings import Settings


@contextmanager
def clean_kb_environment():
    original = {name: value for name, value in os.environ.items() if name.startswith("KB_")}
    for name in original:
        os.environ.pop(name)
    try:
        yield
    finally:
        os.environ.update(original)


def test_service_accepts_relocated_non_d_project_root() -> None:
    with tempfile.TemporaryDirectory() as temporary_root:
        root = Path(temporary_root).resolve()
        assert root.drive.upper() != "D:"
        with clean_kb_environment():
            settings = Settings.from_env(root)

            service = GuidelineService(
                settings, embed_model=MockEmbedding(embed_dim=8)
            )

        assert service.settings.project_root == root
        del service
        gc.collect()


def test_service_wires_local_glossary_below_data_directory() -> None:
    with tempfile.TemporaryDirectory() as temporary_root:
        root = Path(temporary_root).resolve()
        with clean_kb_environment():
            settings = Settings.from_env(root)
            service = GuidelineService(settings, embed_model=MockEmbedding(embed_dim=8))
            terms = service.retriever._load_glossary_terms()

        assert "乳腺癌" in terms
        assert (settings.data_dir / "retrieval" / "bilingual_terms.json").is_file()
        del service
        gc.collect()
