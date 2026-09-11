import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import TypeDecorator

from .crypto import get_cipher


def new_id() -> str:
    return str(uuid.uuid4())


def utcnow() -> datetime:
    return datetime.now(UTC)


class EncryptedText(TypeDecorator):
    impl = LargeBinary
    cache_ok = True

    def process_bind_param(self, value, dialect):
        return None if value is None else get_cipher().encrypt(value.encode())

    def process_result_value(self, value, dialect):
        return None if value is None else get_cipher().decrypt(value).decode()


class EncryptedBytes(TypeDecorator):
    impl = LargeBinary
    cache_ok = True

    def process_bind_param(self, value, dialect):
        return None if value is None else get_cipher().encrypt(value)

    def process_result_value(self, value, dialect):
        return None if value is None else get_cipher().decrypt(value)


class UTCDateTime(TypeDecorator):
    """SQLite drops tzinfo; put it back so aware/naive comparisons can't happen."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        return None if value is None else value.astimezone(UTC)

    def process_result_value(self, value, dialect):
        if value is None or value.tzinfo is not None:
            return value
        return value.replace(tzinfo=UTC)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    email_index: Mapped[str] = mapped_column(String(64), unique=True)
    email: Mapped[str] = mapped_column(EncryptedText)
    password_hash: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class Identifier(Base):
    """Something that identifies the account holder and may be scanned for.

    Emails and phones must be `verified` (the user proved control with a
    code). Names, usernames and images can only be `attested`: we have no way
    to prove them, so they are capped and are only used once the account also
    holds at least one verified identifier.
    """

    __tablename__ = "identifiers"
    __table_args__ = (UniqueConstraint("user_id", "value_index"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(16))
    value: Mapped[str] = mapped_column(EncryptedText)
    value_index: Mapped[str] = mapped_column(String(64))
    image_data: Mapped[bytes | None] = mapped_column(EncryptedBytes, nullable=True)
    status: Mapped[str] = mapped_column(String(16))
    code_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    code_expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    verified_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


class Scan(Base):
    __tablename__ = "scans"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(16))  # exposure | impersonation
    status: Mapped[str] = mapped_column(String(16), default="queued")
    summary: Mapped[str | None] = mapped_column(EncryptedText, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    # Results about other people with the same name: counted, never stored.
    namesakes_excluded: Mapped[int] = mapped_column(Integer, default=0, server_default="0")


class Finding(Base):
    __tablename__ = "findings"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    scan_id: Mapped[str] = mapped_column(ForeignKey("scans.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    category: Mapped[str] = mapped_column(String(32))
    url: Mapped[str] = mapped_column(EncryptedText)
    title: Mapped[str] = mapped_column(EncryptedText)
    broker_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    matched_identifier_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    confidence: Mapped[str] = mapped_column(String(8))
    rationale: Mapped[str] = mapped_column(EncryptedText)
    # likely: an identifier or context detail ties it to the account holder.
    # unclear: only the name does; waits for their verdict before the plan uses it.
    # confirmed: they said "this is me".
    match_status: Mapped[str] = mapped_column(String(16), default="likely", server_default="likely")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class FindingSuppression(Base):
    """A page the account holder said is not about them. Only a blind index
    of the URL is kept, so the table can't be read back as a list of pages."""

    __tablename__ = "finding_suppressions"
    __table_args__ = (UniqueConstraint("user_id", "url_index"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    url_index: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class BreachHit(Base):
    __tablename__ = "breach_hits"
    __table_args__ = (UniqueConstraint("identifier_id", "breach_name"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    identifier_id: Mapped[str] = mapped_column(ForeignKey("identifiers.id", ondelete="CASCADE"))
    breach_name: Mapped[str] = mapped_column(String(128))
    title: Mapped[str] = mapped_column(String(255))
    domain: Mapped[str] = mapped_column(String(255))
    breach_date: Mapped[str] = mapped_column(String(16))
    data_classes: Mapped[list[str]] = mapped_column(JSON, default=list)
    is_verified: Mapped[bool] = mapped_column(Boolean, default=True)
    checked_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class RemediationItem(Base):
    __tablename__ = "remediation_items"
    __table_args__ = (UniqueConstraint("user_id", "dedupe_key"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    dedupe_key: Mapped[str] = mapped_column(String(255))
    source_type: Mapped[str] = mapped_column(String(16))  # finding | breach | baseline
    source_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    action_type: Mapped[str] = mapped_column(String(32))
    priority: Mapped[int] = mapped_column(Integer)  # 0 critical .. 3 low
    title: Mapped[str] = mapped_column(EncryptedText)
    detail: Mapped[str] = mapped_column(EncryptedText)
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    draft: Mapped[str | None] = mapped_column(EncryptedText, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="open")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)


class AuditEvent(Base):
    """Append-only record of who did what. Holds ids, never PII values.

    No foreign key on user_id, so the trail survives account erasure as a
    pseudonymous record.
    """

    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str | None] = mapped_column(String(36), index=True, nullable=True)
    action: Mapped[str] = mapped_column(String(64))
    target_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    target_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
