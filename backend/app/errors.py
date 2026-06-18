from typing import Any


class AppError(Exception):
    """Domain error rendered as {"error": {code, message, details}}."""

    def __init__(
        self,
        code: str,
        message: str,
        status_code: int = 422,
        details: Any | None = None,
    ):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details

    def to_payload(self) -> dict:
        body: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.details is not None:
            body["details"] = self.details
        return {"error": body}


# Room / geometry
ROOM_INVALID = "ROOM_INVALID"
ROOM_TOO_SMALL = "ROOM_TOO_SMALL"
ROOM_TOO_LARGE = "ROOM_TOO_LARGE"
OPENING_INVALID = "OPENING_INVALID"

# Items / products
UNKNOWN_PRODUCT = "UNKNOWN_PRODUCT"
DUPLICATE_INSTANCE = "DUPLICATE_INSTANCE"
TOO_MANY_ITEMS = "TOO_MANY_ITEMS"
PRODUCT_NOT_FOUND = "PRODUCT_NOT_FOUND"

# Guide
UNKNOWN_STEP = "UNKNOWN_STEP"
PLAN_FAILED = "PLAN_FAILED"

# Designs / orders
DESIGN_NOT_FOUND = "DESIGN_NOT_FOUND"
ORDER_NOT_FOUND = "ORDER_NOT_FOUND"
EMPTY_CART = "EMPTY_CART"
STORAGE_ERROR = "STORAGE_ERROR"

# Money
UNSUPPORTED_CURRENCY = "UNSUPPORTED_CURRENCY"

# AI / render
RENDER_DISABLED = "RENDER_DISABLED"
RENDER_REJECTED = "RENDER_REJECTED"
RENDER_FAILED = "RENDER_FAILED"
PNG_TOO_LARGE = "PNG_TOO_LARGE"

VALIDATION_ERROR = "VALIDATION_ERROR"
INTERNAL_ERROR = "INTERNAL_ERROR"
