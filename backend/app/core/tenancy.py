"""Tenant isolation guard rails.

Every API query is written with an explicit `workspace_id` filter. On top of that, a session
bound to a workspace (via `bind_workspace`) gets two automatic safety nets:

1. Reads/updates/deletes on TenantScoped models are filtered to that workspace, so a forgotten
   `where` returns nothing instead of another tenant's data.
2. Flushing a TenantScoped row that belongs to another workspace raises TenantViolation.
"""

import uuid
from typing import Any

from sqlalchemy import event
from sqlalchemy.orm import ORMExecuteState, Session, with_loader_criteria
from sqlalchemy.orm.unitofwork import UOWTransaction

from app.models.base import TenantScoped

_KEY = "workspace_id"


class TenantViolation(RuntimeError):
    pass


def bind_workspace(session: Any, workspace_id: uuid.UUID) -> None:
    """Scope a (sync or async) session to one workspace for the rest of its life."""
    current = session.info.get(_KEY)
    if current is not None and current != workspace_id:
        raise TenantViolation("session is already bound to another workspace")
    session.info[_KEY] = workspace_id


def bound_workspace(session: Any) -> uuid.UUID | None:
    return session.info.get(_KEY)


@event.listens_for(Session, "do_orm_execute")
def _filter_by_workspace(state: ORMExecuteState) -> None:
    workspace_id = state.session.info.get(_KEY)
    if workspace_id is None:
        return
    if not (state.is_select or state.is_update or state.is_delete):
        return
    if state.is_column_load or state.is_relationship_load:
        return
    state.statement = state.statement.options(
        with_loader_criteria(
            TenantScoped,
            lambda cls: cls.workspace_id == workspace_id,
            include_aliases=True,
        )
    )


@event.listens_for(Session, "before_flush")
def _guard_writes(session: Session, flush_context: UOWTransaction, instances: object) -> None:
    workspace_id = session.info.get(_KEY)
    if workspace_id is None:
        return
    for obj in (*session.new, *session.dirty, *session.deleted):
        if not isinstance(obj, TenantScoped):
            continue
        if obj.workspace_id is None and obj in session.new:
            obj.workspace_id = workspace_id
        elif obj.workspace_id != workspace_id:
            raise TenantViolation(f"{type(obj).__name__} belongs to another workspace than this session")
