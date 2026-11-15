"""RFC 9457 Problem Details exception handlers and error utilities."""

from http import HTTPStatus

from fastapi import Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.schemas.errors import ProblemDetails
from app.telemetry import get_current_trace_id


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
    trace_id = (
        getattr(request.state, "trace_id", None)
        or request.headers.get("x-trace-id")
        or get_current_trace_id()
    )
    detail = format_validation_error_detail(exc)

    problem = ProblemDetails(
        type="about:blank",
        title="Unprocessable Entity",
        status=status.HTTP_422_UNPROCESSABLE_CONTENT,
        detail=detail,
        trace_id=trace_id,
    )
    headers = {"X-Trace-ID": trace_id} if trace_id else {}
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        content=problem.model_dump(),
        media_type="application/problem+json",
        headers=headers,
    )


class GenerationFailedException(StarletteHTTPException):
    """Exception raised when report generation fails for both active and fallback models."""

    def __init__(
        self,
        detail: str = "Handover report generation failed for both active and fallback models",
    ) -> None:
        super().__init__(status_code=status.HTTP_502_BAD_GATEWAY, detail=detail)
        self.title = "Generation Failed"


class RateLimitExceededException(StarletteHTTPException):
    """Exception raised when per-client rate limits or global generation caps are exceeded."""

    def __init__(
        self,
        detail: str = "Rate limit exceeded to protect Vertex AI quota",
        retry_after: int = 60,
    ) -> None:
        super().__init__(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=detail,
            headers={"Retry-After": str(max(1, int(retry_after)))},
        )
        self.title = "Too Many Requests"


class ReportNotFoundException(StarletteHTTPException):
    """Exception raised when a handover report is not found by ID."""

    def __init__(
        self,
        report_id: object,
    ) -> None:
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Report with id '{report_id}' not found",
        )
        self.title = "Report Not Found"


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
    trace_id = (
        getattr(request.state, "trace_id", None)
        or request.headers.get("x-trace-id")
        or get_current_trace_id()
    )

    problem = ProblemDetails(
        type="about:blank",
        title=title,
        status=exc.status_code,
        detail=detail,
        trace_id=trace_id,
    )
    headers = dict(getattr(exc, "headers", None) or {})
    if trace_id:
        headers["X-Trace-ID"] = trace_id
    return JSONResponse(
        status_code=exc.status_code,
        content=problem.model_dump(),
        media_type="application/problem+json",
        headers=headers,
    )
