"""小满单源部署入口，保留原底座入口。镜像构建时生成 web/dist。"""
from pathlib import Path

from starlette.responses import RedirectResponse
from starlette.staticfiles import StaticFiles

from app.main import app as backend

DIST = Path(__file__).resolve().parents[3] / "web/dist"
backend.mount("/study", StaticFiles(directory=DIST, html=True, check_dir=False), name="study-web")


class ReleaseApp:
    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and scope["path"] == "/":
            await RedirectResponse("/study/", status_code=307)(scope, receive, send)
        else:
            await backend(scope, receive, send)


app = ReleaseApp()
