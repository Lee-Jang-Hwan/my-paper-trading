"""
프로필 라우트 - 사용자 프로필 CRUD

Clerk 인증 후 clerk_user_id를 기반으로 Supabase user_profiles 테이블을 조회합니다.
"""

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from app.api.dependencies import ClerkUserId
from app.db.supabase_client import get_supabase_client

router = APIRouter(prefix="/api/profile", tags=["profile"])


# ── 요청/응답 모델 ───────────────────────────────────────────

class ProfileResponse(BaseModel):
    """프로필 응답"""
    id: str
    clerk_user_id: str
    display_name: Optional[str] = None
    email: Optional[str] = None
    avatar_url: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class ProfileCreateRequest(BaseModel):
    """프로필 생성/수정 요청"""
    display_name: Optional[str] = Field(None, max_length=50, description="표시 이름")
    email: Optional[str] = Field(None, description="이메일 주소")
    avatar_url: Optional[str] = Field(None, description="프로필 이미지 URL")


# ── 라우트 핸들러 ────────────────────────────────────────────

@router.get("", response_model=ProfileResponse)
async def get_profile(clerk_user_id: ClerkUserId):
    """
    현재 인증된 사용자의 프로필을 조회합니다.

    - Clerk JWT에서 추출한 clerk_user_id로 프로필을 검색합니다.
    - 프로필이 없으면 404를 반환합니다.
    """
    sb = get_supabase_client()

    result = (
        sb.table("user_profiles")
        .select("*")
        .eq("clerk_user_id", clerk_user_id)
        .maybe_single()
        .execute()
    )

    if result.data is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="프로필을 찾을 수 없습니다. 먼저 프로필을 생성해 주세요.",
        )

    return ProfileResponse(**result.data)


@router.post("", response_model=ProfileResponse, status_code=status.HTTP_200_OK)
async def upsert_profile(
    body: ProfileCreateRequest,
    clerk_user_id: ClerkUserId,
):
    """
    프로필을 생성하거나 업데이트합니다 (Upsert).

    - clerk_user_id가 이미 존재하면 업데이트, 없으면 새로 생성합니다.
    - display_name, email, avatar_url 필드를 설정할 수 있습니다.
    """
    sb = get_supabase_client()

    upsert_data = {
        "clerk_user_id": clerk_user_id,
        "updated_at": datetime.utcnow().isoformat(),
    }

    # None이 아닌 필드만 포함
    if body.display_name is not None:
        upsert_data["display_name"] = body.display_name
    if body.email is not None:
        upsert_data["email"] = body.email
    if body.avatar_url is not None:
        upsert_data["avatar_url"] = body.avatar_url

    result = (
        sb.table("user_profiles")
        .upsert(upsert_data, on_conflict="clerk_user_id")
        .execute()
    )

    if not result.data:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="프로필 저장에 실패했습니다.",
        )

    return ProfileResponse(**result.data[0])
