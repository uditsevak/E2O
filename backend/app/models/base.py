import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Enum, ForeignKey, MetaData, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, declared_attr, mapped_column

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)
    type_annotation_map = {  # noqa: RUF012 - SQLAlchemy declarative config
        dict[str, Any]: JSONB,
        list[dict[str, Any]]: JSONB,
        datetime: DateTime(timezone=True),
    }


class IdMixin:
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)


class CreatedAtMixin:
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class TenantScoped:
    """Rows that belong to exactly one workspace.

    Sessions bound to a workspace (session.info["workspace_id"]) automatically filter
    SELECT/UPDATE/DELETE on these models and refuse to write rows for another workspace.
    See app.core.tenancy.
    """

    @declared_attr
    def workspace_id(cls) -> Mapped[uuid.UUID]:
        return mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)


def str_enum(enum_cls: type[enum.StrEnum], length: int = 32) -> Enum:
    """Store enums as plain VARCHAR so new values (new sources, statuses) need no migration."""
    return Enum(
        enum_cls,
        native_enum=False,
        create_constraint=False,
        length=length,
        values_callable=lambda e: [m.value for m in e],
    )
