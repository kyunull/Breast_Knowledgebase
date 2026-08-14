from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.settings import PathOutsideProjectError, Settings


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PATH_ENVIRONMENT_VARIABLES = (
    "KB_DATA_DIR",
    "KB_REGISTRY_DB_PATH",
    "KB_MANAGED_SOURCES_DIR",
    "KB_INDEX_ROOT",
    "KB_MODEL_CACHE_DIR",
    "KB_RUNTIME_CACHE_DIR",
    "KB_MODEL_REVISION",
    "KB_MODEL_LOCAL_FILES_ONLY",
)


class SettingsTests(unittest.TestCase):
    def clean_environment(self):
        return patch.dict(
            os.environ,
            {name: "" for name in PATH_ENVIRONMENT_VARIABLES},
            clear=False,
        )

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
