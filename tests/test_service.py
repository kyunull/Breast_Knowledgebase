from __future__ import annotations

import tempfile
import gc
from pathlib import Path
from unittest.mock import patch

from llama_index.core.embeddings import MockEmbedding

from app.service import GuidelineService
from app.settings import Settings


def test_service_accepts_relocated_non_d_project_root() -> None:
    with tempfile.TemporaryDirectory() as temporary_root:
        root = Path(temporary_root).resolve()
        with patch.dict("os.environ", {}, clear=False):
            settings = Settings.from_env(root)

            service = GuidelineService(
                settings, embed_model=MockEmbedding(embed_dim=8)
            )

        assert service.settings.project_root == root
        del service
        gc.collect()
