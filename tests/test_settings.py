from __future__ import annotations

import os
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from app.settings import PathOutsideProjectError, Settings


PROJECT_ROOT = Path(__file__).resolve().parents[1]
class SettingsTests(unittest.TestCase):
    @contextmanager
    def clean_environment(self):
        original = {
            name: value for name, value in os.environ.items() if name.startswith("KB_")
        }
        for name in original:
            os.environ.pop(name)
        try:
            yield
        finally:
            os.environ.update(original)

    def test_rejects_c_drive_data_directory(self) -> None:
        with self.clean_environment(), patch.dict(
            os.environ,
            {"KB_DATA_DIR": r"C:\not-allowed"},
            clear=False,
        ):
            with self.assertRaisesRegex(PathOutsideProjectError, "KB_DATA_DIR"):
                Settings.from_env(PROJECT_ROOT)

    def test_omitted_project_root_is_discovered(self) -> None:
        with self.clean_environment():
            settings = Settings.from_env()

        self.assertEqual(PROJECT_ROOT, settings.project_root)

    def test_rejects_paths_that_escape_project_with_parent_segments(self) -> None:
        with self.clean_environment(), patch.dict(
            os.environ,
            {"KB_INDEX_ROOT": r"data\..\..\outside"},
            clear=False,
        ):
            with self.assertRaisesRegex(PathOutsideProjectError, "KB_INDEX_ROOT"):
                Settings.from_env(PROJECT_ROOT)

    def test_defaults_and_runtime_environment_stay_in_project(self) -> None:
        with tempfile.TemporaryDirectory(dir=PROJECT_ROOT) as temporary_root:
            root = Path(temporary_root).resolve()
            with self.clean_environment():
                settings = Settings.from_env(root)

            configured_paths = (
                settings.data_dir,
                settings.registry_db_path,
                settings.managed_sources_dir,
                settings.index_root,
                settings.model_cache_dir,
                settings.runtime_cache_dir,
            )
            for configured_path in configured_paths:
                self.assertTrue(configured_path.is_relative_to(root), configured_path)

            runtime_environment = settings.runtime_environment()
            for name in (
                "TEMP",
                "TMP",
                "PIP_CACHE_DIR",
                "HF_HOME",
                "HUGGINGFACE_HUB_CACHE",
                "TRANSFORMERS_CACHE",
                "SENTENCE_TRANSFORMERS_HOME",
                "TORCH_HOME",
            ):
                self.assertIn(name, runtime_environment)
                self.assertTrue(Path(runtime_environment[name]).resolve().is_relative_to(root), name)

            self.assertEqual("cpu", settings.model_device)
            self.assertEqual(4, settings.embedding_batch_size)
            self.assertEqual(512, settings.model_max_seq_length)
            self.assertTrue(settings.bm25_enabled)

    def test_model_revision_defaults_to_pinned_revision(self) -> None:
        with self.clean_environment():
            settings = Settings.from_env(PROJECT_ROOT)

        self.assertEqual(
            "5617a9f61b028005a4858fdac845db406aefb181",
            settings.model_revision,
        )

    def test_clean_environment_prevents_ambient_model_defaults_from_leaking(self) -> None:
        with patch.dict(
            os.environ,
            {
                "KB_MODEL_NAME": "ambient-model",
                "KB_MODEL_DEVICE": "cuda",
                "KB_MODEL_MAX_SEQ_LENGTH": "1024",
                "KB_EMBEDDING_BATCH_SIZE": "8",
                "KB_BM25_ENABLED": "false",
            },
            clear=False,
        ), self.clean_environment():
            settings = Settings.from_env(PROJECT_ROOT)

        self.assertEqual("BAAI/bge-m3", settings.model_name)
        self.assertEqual("cpu", settings.model_device)
        self.assertEqual(512, settings.model_max_seq_length)
        self.assertEqual(4, settings.embedding_batch_size)
        self.assertTrue(settings.bm25_enabled)

    def test_model_revision_environment_override_is_preserved(self) -> None:
        with self.clean_environment(), patch.dict(
            os.environ, {"KB_MODEL_REVISION": "custom-revision"}, clear=False
        ):
            settings = Settings.from_env(PROJECT_ROOT)

        self.assertEqual("custom-revision", settings.model_revision)

    def test_ensure_directories_creates_every_runtime_root(self) -> None:
        with tempfile.TemporaryDirectory(dir=PROJECT_ROOT) as temporary_root:
            root = Path(temporary_root).resolve()
            with self.clean_environment():
                settings = Settings.from_env(root)

            settings.ensure_directories()

            for directory in (
                settings.data_dir,
                settings.registry_db_path.parent,
                settings.managed_sources_dir,
                settings.index_root,
                settings.model_cache_dir,
                settings.runtime_cache_dir,
            ):
                self.assertTrue(directory.is_dir(), directory)

    def test_runtime_environment_paths_are_created_inside_project(self) -> None:
        with tempfile.TemporaryDirectory(dir=PROJECT_ROOT) as temporary_root:
            root = Path(temporary_root).resolve()
            with self.clean_environment():
                settings = Settings.from_env(root)

            settings.ensure_directories()
            runtime_environment = settings.runtime_environment()

            for directory in settings.runtime_directories():
                self.assertTrue(directory.is_dir(), directory)

    def test_local_model_mode_sets_hugging_face_offline_before_model_import(self) -> None:
        with tempfile.TemporaryDirectory(dir=PROJECT_ROOT) as temporary_root:
            root = Path(temporary_root).resolve()
            with self.clean_environment(), patch.dict(
                os.environ, {"KB_MODEL_LOCAL_FILES_ONLY": "true"}, clear=False
            ):
                settings = Settings.from_env(root)

            runtime_environment = settings.runtime_environment()

            self.assertEqual("1", runtime_environment["HF_HUB_OFFLINE"])


if __name__ == "__main__":
    unittest.main()
