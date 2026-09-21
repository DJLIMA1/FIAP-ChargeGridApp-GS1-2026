from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy.exc import IntegrityError

from .auth_page import AUTH_PAGE
from .config import settings
from .modules.auth.routes import router as auth_router
from .modules.charging.routes import router as charging_router
from .modules.coupons.routes import router as coupons_router
from .modules.devices.routes import router as devices_router
from .modules.ownership.routes import router as ownership_router
from .modules.reservations.routes import router as reservations_router
from .modules.stations.routes import router as stations_router
from .modules.users.routes import router as users_router

app = FastAPI(title="ChargeGrid API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings().cors_origins,
    allow_methods=["GET", "POST", "PATCH"],
    allow_headers=["Authorization", "Content-Type", "Idempotency-Key"],
)
app.include_router(auth_router, prefix="/v1")
for router in (
    users_router,
    stations_router,
    reservations_router,
    charging_router,
    devices_router,
    ownership_router,
    coupons_router,
):
    app.include_router(router, prefix="/v1")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/auth/confirmed", response_class=HTMLResponse)
def email_confirmed():
    return HTMLResponse(
        AUTH_PAGE,
        headers={
            "Cache-Control": "no-store",
            "Content-Security-Policy": "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'",
            "Referrer-Policy": "no-referrer",
            "X-Content-Type-Options": "nosniff",
        },
    )


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, error: RequestValidationError):
    fields = [
        {"field": ".".join(str(part) for part in item["loc"] if part != "body"), "message": item["msg"]}
        for item in error.errors()
    ]
    return JSONResponse(
        {"error": {"code": "validation_error", "message": "Dados inválidos", "fields": fields}},
        status_code=422,
    )


@app.exception_handler(HTTPException)
async def http_error(request: Request, error: HTTPException):
    detail = (
        error.detail
        if isinstance(error.detail, dict)
        else {"code": "http_error", "message": str(error.detail)}
    )
    return JSONResponse({"error": detail}, status_code=error.status_code)


@app.exception_handler(IntegrityError)
async def database_conflict(request: Request, error: IntegrityError):
    return JSONResponse(
        {"error": {"code": "conflict", "message": "Operação conflita com registro existente"}},
        status_code=409,
    )


@app.middleware("http")
async def body_limit(request: Request, call_next):
    if request.method in ("POST", "PATCH", "PUT"):
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > 16384:
                return JSONResponse(
                    {"error": {"code": "body_too_large", "message": "Corpo excede 16 KB"}}, status_code=413
                )
        request._body = bytes(body)
    return await call_next(request)
