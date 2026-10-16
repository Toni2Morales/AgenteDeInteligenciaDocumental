from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.api.documents import router as documents_router
from app.api.health import router as health_router
from app.config.settings import settings

app = FastAPI(title=settings.app_name)

app.mount("/static", StaticFiles(directory="src/app/static"), name="static")

templates = Jinja2Templates(directory="src/app/templates")

app.include_router(health_router)
app.include_router(documents_router)


@app.get("/")
async def index(request: Request):
    return templates.TemplateResponse(
        request,
        "index.html",
        {"request": request, "app_name": settings.app_name},
    )
