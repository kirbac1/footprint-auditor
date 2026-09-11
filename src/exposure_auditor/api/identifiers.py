import hashlib
import hmac
import secrets
from datetime import timedelta

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import audit
from ..deps import get_services, get_session, rate_limited_user
from ..identifiers import ATTESTED_KINDS, CONTEXT_CAPS, InvalidIdentifier, index_form, normalize
from ..models import Identifier, User, new_id, utcnow
from ..schemas import IdentifierIn, IdentifierOut, VerifyIn
from ..services import Services

router = APIRouter(prefix="/identifiers", tags=["identifiers"])

CODE_TTL = timedelta(minutes=10)
MAX_ATTEMPTS = 5
_IMAGE_MAGIC = ((b"\xff\xd8\xff", "jpeg"), (b"\x89PNG\r\n\x1a\n", "png"))


def _code_hash(services: Services, identifier_id: str, code: str) -> str:
    return services.cipher.blind_index("verify-code", f"{identifier_id}:{code}")


async def _owned(session: AsyncSession, user: User, identifier_id: str) -> Identifier:
    row = await session.get(Identifier, identifier_id)
    # 404 rather than 403 for other tenants' rows: don't confirm they exist.
    if row is None or row.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "identifier not found")
    return row


async def _check_new(session: AsyncSession, services: Services, user: User, kind: str, index: str) -> None:
    dup = await session.scalar(
        select(Identifier.id).where(Identifier.user_id == user.id, Identifier.value_index == index)
    )
    if dup is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, f"this {kind} is already on your account")
    if kind in ATTESTED_KINDS:
        cap = {
            "name": services.settings.max_attested_names,
            "username": services.settings.max_attested_usernames,
            "image": services.settings.max_attested_images,
            **CONTEXT_CAPS,
        }[kind]
        count = await session.scalar(
            select(func.count()).select_from(Identifier).where(
                Identifier.user_id == user.id, Identifier.kind == kind
            )
        )
        if count >= cap:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                f"at most {cap} {kind}s per account; remove one to add another",
            )


async def _issue_code(services: Services, row: Identifier) -> None:
    code = f"{secrets.randbelow(10**6):06d}"
    row.code_hash = _code_hash(services, row.id, code)
    row.code_expires_at = utcnow() + CODE_TTL
    row.attempts = 0
    await services.sender.send(row.kind, row.value, code)


@router.get("", response_model=list[IdentifierOut])
async def list_identifiers(
    user: User = Depends(rate_limited_user), session: AsyncSession = Depends(get_session)
) -> list[Identifier]:
    rows = await session.scalars(
        select(Identifier).where(Identifier.user_id == user.id).order_by(Identifier.created_at)
    )
    return list(rows.all())


@router.post("", response_model=IdentifierOut, status_code=status.HTTP_201_CREATED)
async def add_identifier(
    body: IdentifierIn,
    user: User = Depends(rate_limited_user),
    services: Services = Depends(get_services),
    session: AsyncSession = Depends(get_session),
) -> Identifier:
    try:
        value = normalize(body.kind, body.value)
    except InvalidIdentifier as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from None
    if body.kind in ATTESTED_KINDS and not body.attest:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"a {body.kind} cannot be verified automatically; set attest=true to confirm it is yours",
        )
    index = services.cipher.blind_index(f"identifier:{body.kind}", index_form(body.kind, value))
    await _check_new(session, services, user, body.kind, index)

    row = Identifier(
        id=new_id(),
        user_id=user.id,
        kind=body.kind,
        value=value,
        value_index=index,
        status="attested" if body.kind in ATTESTED_KINDS else "pending",
    )
    if row.status == "pending":
        await _issue_code(services, row)
    session.add(row)
    audit.record(session, user.id, f"identifier_{row.status}", "identifier", row.id)
    await session.commit()
    return row


@router.post("/image", response_model=IdentifierOut, status_code=status.HTTP_201_CREATED)
async def add_image(
    file: UploadFile = File(...),
    attest: bool = Form(False),
    label: str = Form("photo"),
    user: User = Depends(rate_limited_user),
    services: Services = Depends(get_services),
    session: AsyncSession = Depends(get_session),
) -> Identifier:
    if not attest:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "set attest=true to confirm this is a photo of you"
        )
    limit = services.settings.max_image_bytes
    data = await file.read(limit + 1)
    if len(data) > limit:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, f"images are limited to {limit} bytes")
    is_webp = data[:4] == b"RIFF" and data[8:12] == b"WEBP"
    if not (is_webp or any(data.startswith(magic) for magic, _ in _IMAGE_MAGIC)):
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "upload a JPEG, PNG or WebP image")
    index = services.cipher.blind_index("identifier:image", hashlib.sha256(data).hexdigest())
    await _check_new(session, services, user, "image", index)
    row = Identifier(
        id=new_id(),
        user_id=user.id,
        kind="image",
        value=normalize("image", label),
        value_index=index,
        image_data=data,
        status="attested",
    )
    session.add(row)
    audit.record(session, user.id, "identifier_attested", "identifier", row.id)
    await session.commit()
    return row


@router.post("/{identifier_id}/verify", response_model=IdentifierOut)
async def verify_identifier(
    identifier_id: str,
    body: VerifyIn,
    user: User = Depends(rate_limited_user),
    services: Services = Depends(get_services),
    session: AsyncSession = Depends(get_session),
) -> Identifier:
    row = await _owned(session, user, identifier_id)
    if row.status != "pending" or row.code_hash is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "this identifier is not awaiting verification")
    if row.attempts >= MAX_ATTEMPTS:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "too many attempts; request a new code")
    if row.code_expires_at is None or row.code_expires_at < utcnow():
        raise HTTPException(status.HTTP_410_GONE, "the code has expired; request a new one")
    row.attempts += 1
    if not hmac.compare_digest(row.code_hash, _code_hash(services, row.id, body.code)):
        await session.commit()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "incorrect code")
    row.status = "verified"
    row.verified_at = utcnow()
    row.code_hash = None
    row.code_expires_at = None
    audit.record(session, user.id, "identifier_verified", "identifier", row.id)
    await session.commit()
    return row


@router.post("/{identifier_id}/resend", status_code=status.HTTP_202_ACCEPTED)
async def resend_code(
    identifier_id: str,
    user: User = Depends(rate_limited_user),
    services: Services = Depends(get_services),
    session: AsyncSession = Depends(get_session),
) -> dict:
    row = await _owned(session, user, identifier_id)
    if row.status != "pending":
        raise HTTPException(status.HTTP_409_CONFLICT, "this identifier is not awaiting verification")
    # Codes go to a third party's inbox if someone adds an address that isn't
    # theirs; cap how often we'll message it.
    retry = services.limiter.hit(f"resend:{row.id}", 3, 3600)
    if retry is not None:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "too many codes sent; try again later")
    await _issue_code(services, row)
    await session.commit()
    return {"status": "sent"}


@router.delete("/{identifier_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_identifier(
    identifier_id: str,
    user: User = Depends(rate_limited_user),
    session: AsyncSession = Depends(get_session),
) -> None:
    row = await _owned(session, user, identifier_id)
    await session.delete(row)
    audit.record(session, user.id, "identifier_deleted", "identifier", identifier_id)
    await session.commit()
