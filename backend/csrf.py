import os
import secrets

from fastapi import Request, Response


CSRF_COOKIE_NAME = "archmorph_csrf"
CSRF_HEADER_NAME = "X-CSRF-Token"
UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


def generate_csrf_token() -> str:
    return secrets.token_urlsafe(32)


def csrf_cookie_secure() -> bool:
    environment = (os.getenv("ENVIRONMENT") or os.getenv("ENV") or "development").lower()
    return environment in {"production", "prod", "staging"}


def set_csrf_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        CSRF_COOKIE_NAME,
        token,
        max_age=24 * 60 * 60,
        path="/",
        secure=csrf_cookie_secure(),
        httponly=False,
        samesite="strict",
    )


def request_uses_swa_cookie_auth(request: Request) -> bool:
    if not request.headers.get("x-ms-client-principal"):
        return False
    if request.headers.get("authorization", "").startswith("Bearer "):
        return False
    if request.headers.get("x-api-key"):
        return False
    return True


def requires_csrf_check(request: Request) -> bool:
    return request.method.upper() in UNSAFE_METHODS and request_uses_swa_cookie_auth(request)


def csrf_token_valid(request: Request) -> bool:
    header_token = request.headers.get(CSRF_HEADER_NAME)
    cookie_token = request.cookies.get(CSRF_COOKIE_NAME)
    if not header_token or not cookie_token:
        return False
    return secrets.compare_digest(header_token, cookie_token)