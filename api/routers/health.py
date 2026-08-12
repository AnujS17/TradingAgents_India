from fastapi import APIRouter

from api.schemas import HealthResponse
from api.settings import get_settings

router = APIRouter()


@router.get("/health", response_model=HealthResponse, tags=["ops"])
async def health() -> HealthResponse:
    """Liveness plus dependency visibility.

    Reports "not_configured" rather than failing when Postgres/Redis are
    absent, so the service is deployable and inspectable before the queue and
    database exist.
    """
    settings = get_settings()
    return HealthResponse(
        status="ok",
        version=settings.app_version,
        database="not_configured" if not settings.database_url else "configured",
        queue="not_configured" if not settings.redis_url else "configured",
    )
