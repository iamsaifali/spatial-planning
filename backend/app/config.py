from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env", env_file_encoding="utf-8", extra="ignore"
    )

    app_name: str = "ZORY Spatial Planning API"
    version: str = "0.1.0"
    debug: bool = False

    openai_api_key: str | None = None
    openai_model: str = "gpt-5.5"
    openai_image_model: str = "gpt-image-2"
    reasoning_effort: str = "low"
    llm_timeout_s: float = 8.0
    render_timeout_s: float = 90.0
    render_default_size: str = "1280x896"
    render_max_ref_images: int = 3

    cors_origins: list[str] = ["http://localhost:3000", "http://127.0.0.1:3000"]

    db_path: str = "var/zory.db"
    static_dir: str = "static"
    catalog_path: str = "app/data/catalog.json"
    analysis_cache_size: int = 256
    copy_cache_size: int = 512

    max_render_png_bytes: int = 4 * 1024 * 1024

    # --- Assist planner mode (Recipe Architecture) ----------------------------
    # recipe: DEFAULT - the recipe planner serves production. Proven byte-equivalent to
    #         legacy across golden + broad equivalence tests; routes categories overrides
    #         and unknown room types to legacy; surfaces recipe failures clearly.
    # shadow: legacy is returned to the user while the recipe path runs, is compared, and
    #         divergences are logged (recipe failures swallowed) - for re-validation.
    # legacy: the original hardcoded planner only - the rollback path.
    # Rollback at any time with ASSIST_PLANNER_MODE=legacy (or =shadow).
    assist_planner_mode: Literal["legacy", "recipe", "shadow"] = "recipe"

    # --- scene geometry shared by the 2D canvas and the 3D view ---------------
    wall_thickness_cm: float = 12.0

    # --- money: catalog amounts are stored in base_currency; displays convert
    # --- via currency_rates (units of that currency per 1 unit of base) ------
    supported_currencies: list[str] = ["USD", "SAR"]
    base_currency: str = "USD"
    default_currency: str = "SAR"
    currency_rates: dict[str, float] = {"USD": 1.0, "SAR": 3.75}

    @model_validator(mode="after")
    def _check_currencies(self) -> "Settings":
        if self.base_currency not in self.supported_currencies:
            raise ValueError("BASE_CURRENCY must be one of SUPPORTED_CURRENCIES")
        if self.default_currency not in self.supported_currencies:
            raise ValueError("DEFAULT_CURRENCY must be one of SUPPORTED_CURRENCIES")
        missing = [c for c in self.supported_currencies if c not in self.currency_rates]
        if missing:
            raise ValueError(f"CURRENCY_RATES missing entries for: {missing}")
        if abs(self.currency_rates.get(self.base_currency, 0) - 1.0) > 1e-9:
            raise ValueError("CURRENCY_RATES must map BASE_CURRENCY to 1.0")
        return self

    def rate_for(self, currency: str) -> float:
        return self.currency_rates[currency]

    @property
    def llm_enabled(self) -> bool:
        return bool(self.openai_api_key)

    def resolve(self, rel: str) -> Path:
        p = Path(rel)
        return p if p.is_absolute() else BASE_DIR / p


@lru_cache
def get_settings() -> Settings:
    return Settings()
