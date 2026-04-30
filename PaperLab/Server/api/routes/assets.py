from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

from api.dependencies import get_services

router = APIRouter()


@router.get("/documents/assets/{asset_id}/content")
def get_asset_content(asset_id: str) -> Response:
    """Serve one stored asset binary payload, with Redis as a short-lived cache."""

    services = get_services()
    cached_payload = services.cache_store.load_cached_asset_content(asset_id) if services.cache_store else None
    if cached_payload is not None:
        media_type, content = cached_payload
        return Response(content=content, media_type=media_type)

    stored_payload = services.asset_repository.load_content(asset_id)
    if stored_payload is None:
        raise HTTPException(status_code=404, detail=f"Asset content not found: {asset_id}")

    media_type, content = stored_payload
    if services.cache_store is not None:
        services.cache_store.save_cached_asset_content(
            asset_id,
            media_type=media_type,
            content=content,
        )
    return Response(content=content, media_type=media_type or "application/octet-stream")
