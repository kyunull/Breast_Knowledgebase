from app.api import create_app
from app.service import GuidelineService
from app.settings import Settings


app = create_app(GuidelineService(Settings.from_env()))
