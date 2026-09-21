from fastapi import HTTPException


def fail(code, message, status=409):
    raise HTTPException(status, detail={"code": code, "message": message})
