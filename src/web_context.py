"""Contexto web compartido: templates, DB y ciclo (spec 009)."""

from fastapi.templating import Jinja2Templates

from config import CICLO_START, DB_PATH
from src.static_assets import static_url
from src.training_service import parse_cycle_start

templates = Jinja2Templates(directory="templates")
templates.env.globals["static_url"] = static_url

CICLO_START_DATE = parse_cycle_start(CICLO_START)

__all__ = ["CICLO_START_DATE", "DB_PATH", "templates"]
