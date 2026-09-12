from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class _Out(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=12, max_length=256)


class ResetRequestIn(BaseModel):
    email: str = Field(max_length=320)


class ResetConfirmIn(BaseModel):
    email: str = Field(max_length=320)
    code: str = Field(min_length=6, max_length=6)
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


class ProofStartIn(BaseModel):
    platform: Literal["github", "bluesky"]


class IdentifierOut(_Out):
    id: str
    kind: str
    value: str
    status: str
    created_at: datetime
    verified_at: datetime | None
    proof_platform: str | None = None
    proof_code: str | None = None
    proof_expires_at: datetime | None = None
    # Demo instances only: there is no mailbox to send a code to, so the page
    # shows it. Never set when EA_DEMO_SCANS is off.
    demo_code: str | None = None


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
    model_calls: int = 0
    tool_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    duration_ms: int | None = None
    cost_usd: float | None = None
    findings: list[FindingOut] = []
    # Only with ?trace=true, so following a running scan is one request, not two.
    trace: list["ScanEventOut"] | None = None


class ScanEventOut(_Out):
    seq: int
    kind: str
    name: str
    status: str
    detail: str | None
    offset_ms: int
    duration_ms: int
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_write_tokens: int


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
    jurisdiction: str | None
    items: list[RemediationItemOut]


class ItemUpdateIn(BaseModel):
    status: Literal["open", "sent", "done", "dismissed"]
