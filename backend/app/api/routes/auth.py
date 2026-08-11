from fastapi import APIRouter, Request

from app.api.deps import AuthServiceDep, CurrentUserDep, RateLimiterDep, SettingsDep
from app.api.schemas import LoginRequest, MeResponse, RefreshRequest, TokenPairResponse
from app.application.errors import RateLimitedError

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=TokenPairResponse)
async def login(
    body: LoginRequest,
    request: Request,
    auth: AuthServiceDep,
    limiter: RateLimiterDep,
    settings: SettingsDep,
) -> TokenPairResponse:
    # Brute force protection, keyed by client address and target account so
    # one noisy address cannot lock everyone out.
    client = request.client.host if request.client else "unknown"
    decision = await limiter.allow(
        f"login:{client}:{body.email.lower()}",
        settings.login_attempts_per_minute,
        window_seconds=60,
    )
    if not decision.allowed:
        raise RateLimitedError(
            "Too many sign in attempts. Wait a minute and try again.",
            retry_after_seconds=decision.retry_after_seconds,
        )
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
