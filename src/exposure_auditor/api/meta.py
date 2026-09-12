from fastapi import APIRouter, Depends

from .. import demo
from ..deps import get_services
from ..services import Services
from ..tools.profile_proof import PLATFORMS

router = APIRouter(tags=["meta"])


@router.get("/meta")
async def meta(services: Services = Depends(get_services)) -> dict:
    """What this deployment can do, so the UI can explain a disabled button
    instead of letting the user hit a 503."""
    s = services.settings
    return {
        "demo_scans": s.demo_scans,
        # In demo mode the web is synthetic; the model may still be real.
        "scripted_model": isinstance(services.llm, demo.DemoLLM),
        # A demo instance publishes its shared account: nobody should type
        # their own details into a server that answers with fiction.
        "demo_account": (
            {"email": demo.DEMO_EMAIL, "password": demo.DEMO_PASSWORD}
            # A private password is never published, whatever the other flag says.
            if s.demo_scans and s.demo_account_published and s.demo_password is None
            else None
        ),
        "registration_open": s.registration_open,
        "scans_available": services.llm is not None and services.search is not None,
        "reverse_image_available": services.reverse_image is not None,
        "breach_check_available": s.hibp_api_key is not None,
        "code_delivery": s.verification_delivery,
        "donate_url": s.donate_url,
        "username_proof_required": not s.allow_unproven_usernames,
        "proof_platforms": [
            {"id": p.id, "label": p.label, "profile_url": p.profile_url} for p in PLATFORMS.values()
        ],
        "limits": {
            "names": s.max_attested_names,
            "usernames": s.max_attested_usernames,
            "images": s.max_attested_images,
            "scans_per_day": s.scans_per_day,
        },
    }
