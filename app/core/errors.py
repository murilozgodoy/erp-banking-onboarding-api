"""Erros de negócio com corpo padronizado `{"error": "<CODIGO>", ...}` (contrato do portal)."""
import math

from fastapi import Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


class ApiError(Exception):
    def __init__(self, status_code: int, error: str, **extra) -> None:
        super().__init__(error)
        self.status_code = status_code
        self.body = {"error": error, **extra}


async def api_error_handler(_: Request, exc: ApiError) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content=exc.body)


def _json_safe(value):
    """NaN/Infinity (o json do Python aceita no corpo) não serializam em JSON: viram texto."""
    if isinstance(value, float) and not math.isfinite(value):
        return str(value)
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    return value


async def validation_error_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
    """O 422 padrão do FastAPI, mas sem virar 500 quando o corpo traz NaN/Infinity."""
    return JSONResponse(status_code=422, content={"detail": _json_safe(jsonable_encoder(exc.errors()))})
