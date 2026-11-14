"""RFC 9457 Problem Details exception handlers and error utilities."""

from http import HTTPStatus

from fastapi import Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.schemas.errors import ProblemDetails


def format_validation_error_detail(exc: RequestValidationError) -> str:
    """Format Pydantic / FastAPI validation errors into a human-readable explanation."""
    messages = []
    for err in exc.errors():
        loc = " -> ".join(str(elem) for elem in err.get("loc", []))
        msg = err.get("msg", "Validation error")
        if loc:
            messages.append(f"{loc}: {msg}")
        else:
            messages.append(msg)
    return "; ".join(messages) if messages else "Request validation failed"


async def request_validation_exception_handler(
    request: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    """Exception handler for FastAPI RequestValidationError.

    Returns RFC 9457 ProblemDetails with HTTP 422 and application/problem+json media type.
    """
    trace_id = getattr(request.state, "trace_id", None) or request.headers.get("x-trace-id")
    detail = format_validation_error_detail(exc)

    problem = ProblemDetails(
        type="about:blank",
        title="Unprocessable Entity",
        status=status.HTTP_422_UNPROCESSABLE_CONTENT,
        detail=detail,
        trace_id=trace_id,
    )
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        content=problem.model_dump(),
        media_type="application/problem+json",
    )


class GenerationFailedException(StarletteHTTPException):
    """Exception raised when report generation fails for both active and fallback models."""

    def __init__(
        self,
        detail: str = "Handover report generation failed for both active and fallback models",
    ) -> None:
        super().__init__(status_code=status.HTTP_502_BAD_GATEWAY, detail=detail)
        self.title = "Generation Failed"


async def http_exception_handler(
    request: Request,
    exc: StarletteHTTPException,
) -> JSONResponse:
    """Exception handler for Starlette and FastAPI HTTPExceptions.

    Returns RFC 9457 ProblemDetails with corresponding HTTP status and application/problem+json media type.
    """
    custom_title = getattr(exc, "title", None)
    if custom_title:
        title = custom_title
    elif exc.status_code == 422:
        title = "Unprocessable Entity"
    else:
        try:
            title = HTTPStatus(exc.status_code).phrase
        except ValueError:
            title = "HTTP Error"

    detail = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
    trace_id = getattr(request.state, "trace_id", None) or request.headers.get("x-trace-id")

    problem = ProblemDetails(
        type="about:blank",
        title=title,
        status=exc.status_code,
        detail=detail,
        trace_id=trace_id,
    )
    headers = getattr(exc, "headers", None) or {}
    return JSONResponse(
        status_code=exc.status_code,
        content=problem.model_dump(),
        media_type="application/problem+json",
        headers=headers,
    )
