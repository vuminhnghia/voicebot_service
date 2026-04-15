from fastapi import HTTPException, Security
from fastapi.security import APIKeyHeader

from app.config import get_settings

_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=True)


async def verify_api_key(api_key: str = Security(_api_key_header)) -> str:
    settings = get_settings()
    if api_key not in settings.api_keys:
        raise HTTPException(status_code=403, detail="Invalid API key")
    return api_key
