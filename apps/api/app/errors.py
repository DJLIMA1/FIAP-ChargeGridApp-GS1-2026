from fastapi import HTTPException


def fail(code, message, status=409, **extra):
    """Erro da API ``{"error": {"code", "message", ...}}``; ``extra`` acrescenta campos (ex.: ``reason``)."""
    raise HTTPException(status, detail={"code": code, "message": message, **extra})
