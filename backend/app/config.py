"""
애플리케이션 설정 - 환경변수 로딩 (Pydantic Settings)

루트 .env 파일에서 모든 환경변수를 로드합니다.
"""

from pathlib import Path
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


# backend/app/config.py → 루트는 ../../.env
_ENV_FILE = Path(__file__).resolve().parent.parent.parent / ".env"


class Settings(BaseSettings):
    """전체 애플리케이션 설정"""

    model_config = SettingsConfigDict(
        env_file=str(_ENV_FILE),
        env_file_encoding="utf-8",
        extra="ignore",  # .env에 정의되었지만 여기 없는 변수 무시
    )

    # ── 한국투자증권 OpenAPI ─────────────────────────────────
    KIS_APP_KEY: str = ""
    KIS_APP_SECRET: str = ""
    KIS_ACCOUNT_NO: str = ""
    KIS_ACCOUNT_PRODUCT_CODE: str = "01"
    KIS_BASE_URL: str = "https://openapivts.koreainvestment.com:29443"
    KIS_WS_URL: str = "ws://ops.koreainvestment.com:31000"

    # 2계좌 운영 (선택사항)
    KIS_APP_KEY_2: str = ""
    KIS_APP_SECRET_2: str = ""
    KIS_ACCOUNT_NO_2: str = ""

    # ── Clerk 인증 ───────────────────────────────────────────
    NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY: str = ""
    CLERK_SECRET_KEY: str = ""

    # ── Supabase ─────────────────────────────────────────────
    NEXT_PUBLIC_SUPABASE_URL: str = ""
    SUPABASE_SERVICE_ROLE_KEY: str = ""

    # ── Google Gemini AI ─────────────────────────────────────
    GEMINI_API_KEY: str = ""

    # ── DART 전자공시 ────────────────────────────────────────
    DART_API_KEY: str = ""

    # ── Redis ────────────────────────────────────────────────
    REDIS_URL: str = "redis://localhost:6379"

    # ── FastAPI 서버 ─────────────────────────────────────────
    FASTAPI_HOST: str = "0.0.0.0"
    FASTAPI_PORT: int = 8000
    FASTAPI_WORKERS: int = 1

    # ── CORS ───────────────────────────────────────────────
    CORS_ORIGINS: str = ""  # 쉼표 구분, 예: "https://example.com,https://www2.example.com"

    # ── 앱 설정 ──────────────────────────────────────────────
    PYTHON_ENV: str = "development"
    DEFAULT_INITIAL_CAPITAL: int = 10_000_000

    # ── 에이전트 설정 ────────────────────────────────────────
    AGENT_TICK_INTERVAL: int = 30
    AGENT_DAILY_TOKEN_LIMIT: int = 500_000

    # ── 편의 프로퍼티 ────────────────────────────────────────

    @property
    def supabase_url(self) -> str:
        """백엔드에서 사용하는 Supabase URL"""
        return self.NEXT_PUBLIC_SUPABASE_URL

    @property
    def is_development(self) -> bool:
        return self.PYTHON_ENV == "development"

    @property
    def clerk_domain(self) -> str:
        """
        Clerk publishable key에서 도메인을 추출합니다.
        pk_test_xxxxx 형식에서 xxxxx를 base64 디코딩하면 도메인이 나옵니다.
        예: pk_test_cmljaC1idWxsZnJvZy05MC5jbGVyay5hY2NvdW50cy5kZXYk
        → rich-bullfrog-90.clerk.accounts.dev
        """
        import base64

        pk = self.NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY
        # "pk_test_" 또는 "pk_live_" 이후의 base64 부분 추출
        encoded_part = pk.split("_", 2)[2]  # "pk" + "test" + "base64..."
        # base64 디코딩 (패딩 보정)
        padded = encoded_part + "=" * (-len(encoded_part) % 4)
        decoded = base64.b64decode(padded).decode("utf-8")
        # 끝에 '$' 문자가 붙어 있을 수 있으므로 제거
        return decoded.rstrip("$")

    @property
    def clerk_jwks_url(self) -> str:
        """Clerk JWKS 엔드포인트 URL"""
        return f"https://{self.clerk_domain}/.well-known/jwks.json"

    @property
    def clerk_issuer(self) -> str:
        """Clerk JWT issuer"""
        return f"https://{self.clerk_domain}"


@lru_cache()
def get_settings() -> Settings:
    """설정 싱글턴 (캐시됨)"""
    return Settings()
