from fastapi import APIRouter

from app.api.deps import AuthServiceDep, CurrentUserDep
from app.api.schemas import LoginRequest, MeResponse, RefreshRequest, TokenPairResponse

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=TokenPairResponse)
async def login(body: LoginRequest, auth: AuthServiceDep) -> TokenPairResponse:
    pair = await auth.login(body.email, body.password)
    return TokenPairResponse(
        access_token=pair.access_token,
        refresh_token=pair.refresh_token,
        expires_in=pair.access_expires_in,
    )


@router.post("/refresh", response_model=TokenPairResponse)
async def refresh(body: RefreshRequest, auth: AuthServiceDep) -> TokenPairResponse:
    pair = await auth.refresh(body.refresh_token)
    return TokenPairResponse(
        access_token=pair.access_token,
        refresh_token=pair.refresh_token,
        expires_in=pair.access_expires_in,
    )


@router.get("/me", response_model=MeResponse)
async def me(user: CurrentUserDep) -> MeResponse:
    return MeResponse(
        id=user.id,
        email=user.email,
        role=user.role,
        display_name=user.display_name,
        organization_id=user.organization_id,
    )
