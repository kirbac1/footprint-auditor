from sqlalchemy.ext.asyncio import AsyncSession

from .models import AuditEvent


def record(
    session: AsyncSession,
    user_id: str | None,
    action: str,
    target_type: str | None = None,
    target_id: str | None = None,
) -> None:
    """Stage an audit event in the caller's transaction.

    It commits (or rolls back) together with the change it describes, so the
    log can't claim something happened that didn't.
    """
    session.add(
        AuditEvent(user_id=user_id, action=action, target_type=target_type, target_id=target_id)
    )
