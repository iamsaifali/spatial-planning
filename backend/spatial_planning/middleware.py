"""Bootstrap + request-logging middleware — mirrors the FastAPI startup + request_logging.

Ensures the catalog/DB are loaded before the first request is served, stamps an
X-Request-ID response header, and logs each request the same way the FastAPI app did.
"""

import logging
import time
import uuid

from spatial_planning.bootstrap import ensure_bootstrapped

logger = logging.getLogger("zory")


class BootstrapAndLoggingMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        ensure_bootstrapped()
        request_id = request.headers.get("X-Request-ID", uuid.uuid4().hex[:8])
        start = time.perf_counter()
        response = self.get_response(request)
        elapsed_ms = (time.perf_counter() - start) * 1000
        response["X-Request-ID"] = request_id
        if not request.path.startswith("/static"):
            logger.info(
                "%s %s -> %d (%.0f ms) [%s]",
                request.method, request.path, response.status_code, elapsed_ms, request_id,
            )
        return response
