"""Erros de negócio com corpo padronizado `{"error": "<CODIGO>", ...}` (contrato do portal)."""
from fastapi import Request
from fastapi.responses import JSONResponse


class ApiError(Exception):
    def __init__(self, status_code: int, error: str, **extra) -> None:
        super().__init__(error)
        self.status_code = status_code
        self.body = {"error": error, **extra}


async def api_error_handler(_: Request, exc: ApiError) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content=exc.body)
