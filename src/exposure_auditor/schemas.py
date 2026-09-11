from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class _Out(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=12, max_length=256)


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"  # noqa: S105 - OAuth2 token type, not a secret


class IdentifierIn(BaseModel):
    kind: Literal["email", "phone", "name", "username", "city", "birth_year", "workplace"]
    value: str = Field(min_length=1, max_length=320)
    attest: bool = Field(
        default=False,
        description="Required for name and username: you confirm the identifier is yours.",
    )


class VerifyIn(BaseModel):
    code: str = Field(pattern=r"^\d{6}$")


class IdentifierOut(_Out):
    id: str
    kind: str
    value: str
    status: str
    created_at: datetime
    verified_at: datetime | None


class FindingOut(_Out):
    id: str
    category: str
    url: str
    title: str
    broker_id: str | None
    matched_identifier_ids: list[str]
    confidence: str
    rationale: str
    match_status: str


class ScanOut(_Out):
    id: str
    kind: str
    status: str
    summary: str | None
    error: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    namesakes_excluded: int = 0
    findings: list[FindingOut] = []


class ScanAccepted(BaseModel):
    scan_id: str
    status: str


class BreachOut(_Out):
    identifier_id: str
    breach_name: str
    title: str
    domain: str
    breach_date: str
    data_classes: list[str]
    is_verified: bool


class BreachCheckOut(BaseModel):
    checked_identifiers: int
    breaches: list[BreachOut]


class PasswordRangeIn(BaseModel):
    sha1_prefix: str = Field(pattern=r"^[0-9A-Fa-f]{5}$")


class RangeEntry(BaseModel):
    suffix: str
    count: int


class PasswordRangeOut(BaseModel):
    prefix: str
    suffixes: list[RangeEntry]


class RemediationItemOut(_Out):
    id: str
    action_type: str
    priority: int
    title: str
    detail: str
    url: str | None
    draft: str | None
    status: str
    source_type: str
    source_id: str | None


class RemediationPlanOut(BaseModel):
    jurisdiction: str
    items: list[RemediationItemOut]


class ItemUpdateIn(BaseModel):
    status: Literal["open", "sent", "done", "dismissed"]
