from fastapi import APIRouter

from app.config import get_settings
from app.models.geometry import StrictModel

router = APIRouter(tags=["config"])


class CurrencyConfig(StrictModel):
    supported: list[str]
    base: str
    default: str
    rates: dict[str, float]  # units of currency per 1 unit of base


class SceneConfig(StrictModel):
    wall_thickness_cm: float  # shared by the 2D canvas and the 3D view


class AppConfigResponse(StrictModel):
    currency: CurrencyConfig
    scene: SceneConfig


@router.get("/config", response_model=AppConfigResponse)
def app_config() -> AppConfigResponse:
    settings = get_settings()
    return AppConfigResponse(
        currency=CurrencyConfig(
            supported=settings.supported_currencies,
            base=settings.base_currency,
            default=settings.default_currency,
            rates=settings.currency_rates,
        ),
        scene=SceneConfig(wall_thickness_cm=settings.wall_thickness_cm),
    )
