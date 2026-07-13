"""DRF exception handler that reproduces the FastAPI error contract exactly.

FastAPI emitted three shapes:
  - AppError                 -> exc.to_payload() with exc.status_code
  - RequestValidationError   -> 422 {"error": {code, message, details:[{loc, message}]}}
  - any other Exception      -> 500 {"error": {code: INTERNAL_ERROR, message}}

We keep those byte-for-byte. Request-body validation now surfaces as a pydantic
ValidationError (raised by `Model.model_validate(request.data)` in the views); we prefix
each error `loc` with "body" so it matches FastAPI's body-validation loc.
"""

import logging

from pydantic import ValidationError as PydanticValidationError
from rest_framework.exceptions import ParseError
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_default

from spatial_planning.errors import INTERNAL_ERROR, VALIDATION_ERROR, AppError

logger = logging.getLogger("zory")


def zory_exception_handler(exc, context):
    if isinstance(exc, AppError):
        return Response(exc.to_payload(), status=exc.status_code)

    if isinstance(exc, PydanticValidationError):
        details = [
            {"loc": ["body", *[str(p) for p in err.get("loc", [])]], "message": err.get("msg", "")}
            for err in exc.errors()[:20]
        ]
        return Response(
            {
                "error": {
                    "code": VALIDATION_ERROR,
                    "message": "The request payload is invalid.",
                    "details": details,
                }
            },
            status=422,
        )

    # Malformed JSON body: DRF raises ParseError (400 {"detail"}). FastAPI returned
    # 422 with the {"error": {...}} validation envelope — match that instead.
    if isinstance(exc, ParseError):
        return Response(
            {
                "error": {
                    "code": VALIDATION_ERROR,
                    "message": "The request payload is invalid.",
                    "details": [],
                }
            },
            status=422,
        )

    # Let DRF handle its own exceptions (e.g. 405 Method Not Allowed) unchanged.
    response = drf_default(exc, context)
    if response is not None:
        return response

    logger.exception("Unhandled error")
    return Response(
        {"error": {"code": INTERNAL_ERROR, "message": "Something went wrong on our side."}},
        status=500,
    )
