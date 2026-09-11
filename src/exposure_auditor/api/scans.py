from datetime import timedelta

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import audit
from ..deps import get_services, get_session, rate_limited_user
from ..models import Finding, Scan, User, new_id, utcnow
from ..scans import ScopeUnavailable, load_scope, run_scan
from ..schemas import FindingOut, ScanAccepted, ScanOut
from ..services import Services

router = APIRouter(tags=["scans"])


async def _enqueue(
    kind: str, user: User, services: Services, session: AsyncSession, background: BackgroundTasks
) -> ScanAccepted:
    if services.llm is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "the scan model is not configured")
    try:
        _, images = await load_scope(session, user.id, kind)
    except ScopeUnavailable as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None
    # Without a way to look anything up, a scan is a billed model
    # conversation that can only report it found nothing.
    can_image_search = kind == "impersonation" and images and services.reverse_image is not None
    if services.search is None and not can_image_search:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "web search is not configured (set EA_BRAVE_API_KEY)"
        )

    running = await session.scalar(
        select(Scan.id).where(Scan.user_id == user.id, Scan.status.in_(("queued", "running")))
    )
    if running is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "a scan is already in progress")
    recent = await session.scalar(
        select(func.count()).select_from(Scan).where(
            Scan.user_id == user.id, Scan.created_at >= utcnow() - timedelta(days=1)
        )
    )
    if recent >= services.settings.scans_per_day:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "daily scan limit reached")

    scan = Scan(id=new_id(), user_id=user.id, kind=kind, status="queued")
    session.add(scan)
    audit.record(session, user.id, f"scan_requested:{kind}", "scan", scan.id)
    await session.commit()
    # In-process for the MVP. In production this becomes an SQS message
    # consumed by a worker, so a deploy doesn't kill scans mid-run.
    background.add_task(run_scan, services, scan.id)
    return ScanAccepted(scan_id=scan.id, status=scan.status)


@router.post("/scan", response_model=ScanAccepted, status_code=status.HTTP_202_ACCEPTED)
async def start_exposure_scan(
    background: BackgroundTasks,
    user: User = Depends(rate_limited_user),
    services: Services = Depends(get_services),
    session: AsyncSession = Depends(get_session),
) -> ScanAccepted:
    return await _enqueue("exposure", user, services, session, background)


@router.post("/impersonation-check", response_model=ScanAccepted, status_code=status.HTTP_202_ACCEPTED)
async def start_impersonation_check(
    background: BackgroundTasks,
    user: User = Depends(rate_limited_user),
    services: Services = Depends(get_services),
    session: AsyncSession = Depends(get_session),
) -> ScanAccepted:
    return await _enqueue("impersonation", user, services, session, background)


@router.get("/scans", response_model=list[ScanOut])
async def list_scans(
    user: User = Depends(rate_limited_user), session: AsyncSession = Depends(get_session)
) -> list[Scan]:
    rows = await session.scalars(
        select(Scan).where(Scan.user_id == user.id).order_by(Scan.created_at.desc())
    )
    return list(rows.all())


@router.get("/scan/{scan_id}", response_model=ScanOut)
async def get_scan(
    scan_id: str, user: User = Depends(rate_limited_user), session: AsyncSession = Depends(get_session)
) -> ScanOut:
    scan = await session.get(Scan, scan_id)
    if scan is None or scan.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "scan not found")
    findings = await session.scalars(
        select(Finding).where(Finding.scan_id == scan.id).order_by(Finding.created_at)
    )
    out = ScanOut.model_validate(scan)
    out.findings = [FindingOut.model_validate(f) for f in findings.all()]
    return out
