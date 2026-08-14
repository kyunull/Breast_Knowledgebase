from pathlib import Path

from app.api import create_app
from app.service import GuidelineService
from app.settings import Settings


PROJECT_ROOT = Path(r"D:\coding\knowledgebase")
app = create_app(GuidelineService(Settings.from_env(PROJECT_ROOT)))
