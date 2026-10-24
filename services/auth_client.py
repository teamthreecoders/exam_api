"""Thin client for the external authentication service.

This platform never implements its own signup/login/password logic -- it
proxies to an existing FastAPI auth service (see ../AUTH_INTEGRATION.md).
"""
import httpx

from core.config import settings


class AuthServiceError(Exception):
    def __init__(self, status_code: int, msg: str, issue: str | None = None):
        self.status_code = status_code
        self.msg = msg
        self.issue = issue
        super().__init__(msg)


def _unwrap(response: httpx.Response) -> dict:
    try:
        body = response.json()
    except ValueError as exc:
        raise AuthServiceError(502, "Auth service returned a non-JSON response") from exc

    if not body.get("success"):
        error = body.get("error") or {}
        raise AuthServiceError(response.status_code, body.get("msg", "Auth service error"), error.get("issue"))
    return body.get("data") or {}


class _Shared:
    """Lets existing `with self._client() as client` call sites use the shared
    client without closing it on exit."""

    def __init__(self, client: httpx.Client) -> None:
        self._c = client

    def __enter__(self) -> httpx.Client:
        return self._c

    def __exit__(self, *exc) -> None:
        return None


class AuthServiceClient:
    def __init__(self) -> None:
        self._base_url = settings.AUTH_SERVICE_BASE_URL
        # One long-lived client so keep-alive connections are reused; a fresh
        # client per call pays a full DNS + TCP + TLS handshake every time.
        self._http = httpx.Client(base_url=self._base_url, timeout=settings.AUTH_SERVICE_TIMEOUT_SECONDS)

    def _client(self) -> "_Shared":
        return _Shared(self._http)

    def signup(self, payload: dict) -> dict:
        with self._client() as client:
            return _unwrap(client.post("/v1/auth/signup", json=payload))

    def login(self, payload: dict) -> dict:
        with self._client() as client:
            return _unwrap(client.post("/v1/auth/otp/login", json=payload))

    def verify_2fa(self, payload: dict) -> dict:
        with self._client() as client:
            return _unwrap(client.post("/v1/auth/otp/login/2fa_verify", json=payload))

    def forgot_password(self, payload: dict) -> dict:
        with self._client() as client:
            return _unwrap(client.post("/v1/auth/forgot-password", json=payload))

    def get_me(self, token: str) -> dict:
        with self._client() as client:
            return _unwrap(client.post("/v1/auth/me", headers={"Authorization": f"Bearer {token}"}))

    def logout(self, token: str | None) -> None:
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        with self._client() as client:
            client.delete("/v1/auth/logout", headers=headers)


auth_service_client = AuthServiceClient()
