from fastapi import APIRouter, Depends

from ..deps import get_services
from ..services import Services

router = APIRouter(tags=["meta"])


@router.get("/meta")
async def meta(services: Services = Depends(get_services)) -> dict:
    """What this deployment can do, so the UI can explain a disabled button
    instead of letting the user hit a 503."""
    s = services.settings
    return {
        "demo_scans": s.demo_scans,
        "scans_available": services.llm is not None and services.search is not None,
        "reverse_image_available": services.reverse_image is not None,
        "breach_check_available": s.hibp_api_key is not None,
        "code_delivery": s.verification_delivery,
        "donate_url": s.donate_url,
        "limits": {
            "names": s.max_attested_names,
            "usernames": s.max_attested_usernames,
            "images": s.max_attested_images,
            "scans_per_day": s.scans_per_day,
        },
    }
