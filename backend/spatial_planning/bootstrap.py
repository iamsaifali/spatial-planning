"""Lazy startup — the Django equivalent of the FastAPI `lifespan`.

Loads the catalog into memory lazily on the first request (guarded + thread-safe), so it
never runs during management commands and stays behind the existing `get_repository()`
seam — the catalog can later be swapped to a DB-backed loader without touching the engine.
The assist-only app is otherwise stateless (no SQLite / persistence).
"""

import logging
import threading

from spatial_planning.config import get_settings
from spatial_planning.services.catalog import CatalogRepository, set_repository

logger = logging.getLogger("zory")

_lock = threading.Lock()
_done = False


def ensure_bootstrapped() -> None:
    global _done
    if _done:
        return
    with _lock:
        if _done:
            return
        settings = get_settings()
        static_dir = settings.resolve(settings.static_dir)
        static_dir.mkdir(parents=True, exist_ok=True)
        (static_dir / "products").mkdir(parents=True, exist_ok=True)

        repo = CatalogRepository.load(settings.resolve(settings.catalog_path), static_dir)
        set_repository(repo)
        logger.info("Catalog loaded: %d products", len(repo.all()))
        _done = True
