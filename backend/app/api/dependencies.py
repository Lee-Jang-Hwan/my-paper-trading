"""
인증 의존성 - Clerk JWT 검증

Clerk의 JWKS 엔드포인트에서 공개키를 가져와 RS256으로 JWT를 검증합니다.
clerk_user_id (sub claim)를 추출하여 라우트 핸들러에 주입합니다.
"""

import time
from typing import Annotated

import httpx
import jwt
from jwt import PyJWKClient, PyJWK
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import Settings, get_settings

# ── Bearer 토큰 스킴 ────────────────────────────────────────
_bearer_scheme = HTTPBearer(
    scheme_name="Clerk JWT",
    description="Clerk에서 발급한 Bearer 토큰",
)


# ── JWKS 캐시 ────────────────────────────────────────────────

class _JWKSCache:
    """Clerk JWKS 공개키를 TTL 기반으로 캐시합니다."""

    def __init__(self, ttl_seconds: int = 3600):
        self._ttl = ttl_seconds
        self._jwk_client: PyJWKClient | None = None
        self._last_fetched: float = 0.0
        self._jwks_url: str = ""

    def _ensure_client(self, jwks_url: str) -> PyJWKClient:
        """JWKS 클라이언트를 초기화하거나 TTL 만료 시 재생성합니다."""
        now = time.time()
        if (
            self._jwk_client is None
            or self._jwks_url != jwks_url
            or (now - self._last_fetched) > self._ttl
        ):
            self._jwk_client = PyJWKClient(
                uri=jwks_url,
                cache_keys=True,
                lifespan=self._ttl,
            )
            self._jwks_url = jwks_url
            self._last_fetched = now
        return self._jwk_client

    def get_signing_key(self, token: str, jwks_url: str) -> PyJWK:
        """토큰 헤더의 kid에 매칭되는 서명 키를 반환합니다."""
        client = self._ensure_client(jwks_url)
        return client.get_signing_key_from_jwt(token)


_jwks_cache = _JWKSCache(ttl_seconds=3600)


# ── JWT 검증 의존성 ──────────────────────────────────────────

async def verify_clerk_token(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(_bearer_scheme)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> str:
    """
    Clerk JWT를 검증하고 clerk_user_id (sub claim)를 반환합니다.

    사용법:
        @router.get("/api/profile")
        async def get_profile(clerk_user_id: str = Depends(verify_clerk_token)):
            ...
    """
    token = credentials.credentials

    # JWKS에서 서명키 획득
    try:
        signing_key = _jwks_cache.get_signing_key(
            token=token,
            jwks_url=settings.clerk_jwks_url,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"JWKS 키를 가져올 수 없습니다: {exc}",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # JWT 디코딩 및 검증
    try:
        payload = jwt.decode(
            token,
            key=signing_key.key,
            algorithms=["RS256"],
            issuer=settings.clerk_issuer,
            leeway=30,  # 시계 차이(clock skew) 30초 허용
            options={
                "verify_aud": False,  # Clerk은 aud가 없을 수 있음
                "verify_exp": True,
                "verify_iss": True,
            },
        )
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="토큰이 만료되었습니다.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except jwt.InvalidIssuerError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="잘못된 토큰 발급자입니다.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except jwt.PyJWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"토큰 검증에 실패했습니다: {exc}",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # sub claim에서 clerk_user_id 추출
    clerk_user_id: str | None = payload.get("sub")
    if not clerk_user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="토큰에 사용자 정보(sub)가 없습니다.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return clerk_user_id


# ── 타입 별칭 (라우트에서 간편하게 사용) ──────────────────────
ClerkUserId = Annotated[str, Depends(verify_clerk_token)]


# ── WebSocket용 JWT 검증 (Depends 없이 직접 호출) ────────────

def verify_ws_token(token: str) -> str | None:
    """
    WebSocket 연결 시 JWT를 검증합니다.
    성공 시 clerk_user_id 반환, 실패 시 None 반환.
    """
    settings = get_settings()
    try:
        signing_key = _jwks_cache.get_signing_key(
            token=token,
            jwks_url=settings.clerk_jwks_url,
        )
        payload = jwt.decode(
            token,
            key=signing_key.key,
            algorithms=["RS256"],
            issuer=settings.clerk_issuer,
            leeway=30,  # 시계 차이(clock skew) 30초 허용
            options={
                "verify_aud": False,
                "verify_exp": True,
                "verify_iss": True,
            },
        )
        return payload.get("sub")
    except Exception:
        return None
