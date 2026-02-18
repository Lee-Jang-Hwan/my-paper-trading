"""
Supabase 클라이언트 초기화

service_role 키를 사용하므로 RLS를 바이패스합니다.
모든 쿼리에서 clerk_user_id로 직접 필터링해야 합니다.
"""

from supabase import create_client, Client

from app.config import get_settings


_client: Client | None = None


def get_supabase_client() -> Client:
    """Supabase 클라이언트 싱글턴을 반환합니다."""
    global _client
    if _client is None:
        settings = get_settings()
        _client = create_client(
            supabase_url=settings.supabase_url,
            supabase_key=settings.SUPABASE_SERVICE_ROLE_KEY,
        )
    return _client


def reset_supabase_client() -> None:
    """테스트 등에서 클라이언트를 리셋합니다."""
    global _client
    _client = None
