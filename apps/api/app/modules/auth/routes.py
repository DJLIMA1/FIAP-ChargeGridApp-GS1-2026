import time
from datetime import timedelta

import httpx
from fastapi import APIRouter, Depends, Header, Request
from sqlalchemy.dialects.postgresql import insert

from ...config import settings
from ...database import db_session
from ...errors import fail
from ...models import RequestLimit, now
from ...schemas import (
    AuthInput,
    CodeInput,
    PasswordInput,
    PasswordUpdateInput,
    RefreshInput,
    RegisterInput,
    ResetInput,
)
from ...security import current_user, digest

router = APIRouter(prefix="/auth")


def limit(db, key, maximum=15, seconds=60):
    window = int(time.time()) // seconds
    value = db.execute(
        insert(RequestLimit)
        .values(key=digest(key), window=window, count=1, expires_at=now() + timedelta(seconds=seconds * 2))
        .on_conflict_do_update(
            index_elements=[RequestLimit.key, RequestLimit.window], set_={"count": RequestLimit.count + 1}
        )
        .returning(RequestLimit.count)
    ).scalar_one()
    # Rate limits survive even when the protected operation is rejected.
    db.commit()
    if value > maximum:
        fail("rate_limited", "Aguarde antes de repetir", 429)


def auth_limit(request: Request, db=Depends(db_session)):
    limit(db, "auth:" + (request.client.host if request.client else "unknown"), maximum=20)


async def provider(
    method,
    path,
    body=None,
    token=None,
    generic_message=None,
    masked_error_codes=(),
    masked_response=None,
    passthrough_success=False,
):
    headers = {"apikey": settings().supabase_anon_key}
    if token:
        headers["Authorization"] = "Bearer " + token
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            result = await client.request(
                method, settings().supabase_url + "/auth/v1" + path, json=body, headers=headers
            )
    except httpx.HTTPError:
        fail("auth_unavailable", "Autenticação temporariamente indisponível", 503)
    if result.status_code >= 400:
        try:
            rejected = result.json()
        except ValueError:
            rejected = {}
        provider_code = (
            rejected.get("code") or rejected.get("error_code") if isinstance(rejected, dict) else None
        )
        if provider_code in masked_error_codes:
            return masked_response or {"message": generic_message}
        if result.status_code == 429 or provider_code in {
            "over_email_send_rate_limit",
            "over_request_rate_limit",
        }:
            fail("rate_limited", "Limite de envio atingido; tente novamente mais tarde", 429)
        if provider_code == "weak_password":
            fail(
                "weak_password",
                "Escolha uma senha mais forte, com pelo menos 8 caracteres; evite senhas comuns",
                422,
            )
        if provider_code in {"email_address_invalid", "validation_failed"}:
            fail("invalid_email", "Informe um e-mail válido", 422)
        if provider_code == "signup_disabled":
            fail("signup_disabled", "Cadastro temporariamente indisponível", 503)
        if provider_code in {"email_address_not_authorized", "email_provider_disabled"}:
            fail(
                "email_unavailable",
                "Envio de e-mail indisponível no momento. Tente novamente mais tarde.",
                503,
            )
        if generic_message is not None:
            fail(
                "auth_unavailable", "Não foi possível enviar o e-mail agora; tente novamente mais tarde", 503
            )
        if result.status_code >= 500:
            fail("auth_unavailable", "Autenticação temporariamente indisponível; tente novamente", 503)
        if provider_code == "email_not_confirmed":
            fail(
                "email_not_confirmed",
                "Confirme seu e-mail para entrar. Você pode solicitar uma nova mensagem.",
                401,
            )
        fail("auth_rejected", "Credenciais ou código inválidos", 401 if result.status_code < 500 else 503)
    if generic_message is not None and not passthrough_success:
        return {"message": generic_message}
    try:
        response = result.json() if result.content else {"message": "Concluído"}
    except ValueError:
        fail("auth_unavailable", "Autenticação temporariamente indisponível; tente novamente", 503)
    if not isinstance(response, dict):
        fail("auth_unavailable", "Autenticação temporariamente indisponível; tente novamente", 503)
    return response


@router.post("/register", dependencies=[Depends(auth_limit)])
async def register(data: RegisterInput):
    result = await provider(
        "POST",
        "/signup",
        {
            "email": data.email,
            "password": data.password,
            "data": {"name": data.name, "account_type": data.account_type},
        },
        masked_error_codes=("user_already_exists",),
        masked_response={"message": "Cadastro recebido"},
        passthrough_success=True,
    )
    # A provider may enable email confirmation without a new app deployment.
    # A neutral existing-account response is not a promise that mail was sent.
    result["requires_email_confirmation"] = not result.get("access_token") and bool(
        result.get("id") or result.get("user")
    )
    return result


@router.post("/verify-email", dependencies=[Depends(auth_limit)])
async def verify(data: CodeInput):
    return await provider("POST", "/verify", {"email": data.email, "token": data.code, "type": "signup"})


@router.post("/resend-signup", dependencies=[Depends(auth_limit)])
async def resend_signup(data: AuthInput, db=Depends(db_session)):
    limit(db, "resend-signup:" + data.email.casefold(), maximum=1, seconds=60)
    return await provider(
        "POST",
        "/resend",
        {"email": data.email, "type": "signup"},
        generic_message="Se a conta puder receber mensagens, uma confirmação será enviada",
    )


@router.post("/login", dependencies=[Depends(auth_limit)])
async def login(data: PasswordInput):
    return await provider("POST", "/token?grant_type=password", data.model_dump())


@router.post("/refresh", dependencies=[Depends(auth_limit)])
async def refresh(data: RefreshInput):
    return await provider("POST", "/token?grant_type=refresh_token", data.model_dump())


@router.post("/logout")
async def logout(user=Depends(current_user), authorization: str = Header()):
    return await provider("POST", "/logout?scope=local", token=authorization[7:])


@router.post("/password/forgot", dependencies=[Depends(auth_limit)])
async def forgot(data: AuthInput):
    return await provider(
        "POST",
        "/recover",
        data.model_dump(),
        generic_message="Se a conta existir, você receberá instruções para recuperar a senha",
    )


@router.post("/password/reset", dependencies=[Depends(auth_limit)])
async def reset(data: ResetInput):
    verified = await provider(
        "POST", "/verify", {"email": data.email, "token": data.code, "type": "recovery"}
    )
    await provider("PUT", "/user", {"password": data.password}, token=verified["access_token"])
    await provider("POST", "/logout?scope=global", token=verified["access_token"])
    return {"message": "Senha alterada; faça login"}


@router.post("/password/update", dependencies=[Depends(auth_limit)])
async def update_password(
    data: PasswordUpdateInput, user=Depends(current_user), authorization: str = Header()
):
    """Finish recovery from the short-lived bearer token delivered in the email link."""
    await provider("PUT", "/user", {"password": data.password}, token=authorization[7:])
    await provider("POST", "/logout?scope=global", token=authorization[7:])
    return {"message": "Senha alterada; faça login"}
