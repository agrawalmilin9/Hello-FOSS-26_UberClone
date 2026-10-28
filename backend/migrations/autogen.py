"""How Alembic compares and writes our custom column types (used by env.py and the migration tests)."""
from __future__ import annotations

import sqlalchemy as sa

from backend.app.models import UTCDateTime


def render_item(type_: str, obj, autogen_context):
    """Write UTCDateTime into migrations as a plain timestamptz, so migrations never import app code."""
    if type_ == "type" and isinstance(obj, UTCDateTime):
        return "sa.DateTime(timezone=True)"
    return False  # default rendering


def compare_type(context, inspected_column, metadata_column, inspected_type, metadata_type):
    """Don't report our own column types as changed: the database only stores what they're built on."""
    if isinstance(metadata_type, UTCDateTime):
        return not isinstance(inspected_type, sa.DateTime)
    if isinstance(metadata_type, sa.Enum) and not metadata_type.native_enum:
        # Stored as VARCHAR(length); a change only matters if the length changed.
        return not isinstance(inspected_type, sa.String) or inspected_type.length != metadata_type.length
    return None  # default comparison
