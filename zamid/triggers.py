"""
Database triggers that keep ZAM IDs permanent even against raw SQL and
QuerySet.update(): rows are never deleted, the code never changes, targets are
set only while the row is reserved, and the lifecycle only moves forward.

Migrations pass the target columns that exist at that point in history, so a
later migration that adds a target column calls install() again with the new list.
SQLite drops triggers when Django rebuilds a table, so any migration that alters
zamid_zamid on SQLite must call install() again as well.
"""
TABLE = "zamid_zamid"
FORWARD_ONLY = (
    "(OLD.status = 'retired' AND NEW.status <> 'retired')"
    " OR (OLD.status = 'assigned' AND NEW.status = 'reserved')"
)


def _postgres(columns):
    changed = " OR ".join(f"NEW.{c} IS DISTINCT FROM OLD.{c}" for c in columns)
    return [
        f"""
        CREATE OR REPLACE FUNCTION zamid_guard() RETURNS trigger AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'ZAM IDs are never deleted' USING ERRCODE = 'integrity_constraint_violation';
            END IF;
            IF NEW.code <> OLD.code THEN
                RAISE EXCEPTION 'The code of a ZAM ID cannot change' USING ERRCODE = 'integrity_constraint_violation';
            END IF;
            IF OLD.status <> 'reserved' AND ({changed}) THEN
                RAISE EXCEPTION 'The target of a claimed ZAM ID cannot change' USING ERRCODE = 'integrity_constraint_violation';
            END IF;
            IF {FORWARD_ONLY} THEN
                RAISE EXCEPTION 'The lifecycle of a ZAM ID only moves forward' USING ERRCODE = 'integrity_constraint_violation';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """,
        f"DROP TRIGGER IF EXISTS zamid_guard_update ON {TABLE}",
        f"DROP TRIGGER IF EXISTS zamid_guard_delete ON {TABLE}",
        f"CREATE TRIGGER zamid_guard_update BEFORE UPDATE ON {TABLE} FOR EACH ROW EXECUTE FUNCTION zamid_guard()",
        f"CREATE TRIGGER zamid_guard_delete BEFORE DELETE ON {TABLE} FOR EACH ROW EXECUTE FUNCTION zamid_guard()",
    ]


def _sqlite(columns):
    changed = " OR ".join(f"NEW.{c} IS NOT OLD.{c}" for c in columns)
    return [
        "DROP TRIGGER IF EXISTS zamid_guard_update",
        "DROP TRIGGER IF EXISTS zamid_guard_delete",
        f"""
        CREATE TRIGGER zamid_guard_update BEFORE UPDATE ON {TABLE}
        WHEN NEW.code <> OLD.code OR (OLD.status <> 'reserved' AND ({changed})) OR {FORWARD_ONLY}
        BEGIN SELECT RAISE(ABORT, 'ZAM IDs are permanent: code, target and lifecycle cannot be changed back'); END
        """,
        f"""
        CREATE TRIGGER zamid_guard_delete BEFORE DELETE ON {TABLE}
        BEGIN SELECT RAISE(ABORT, 'ZAM IDs are never deleted'); END
        """,
    ]


def _postgres_drop():
    return [
        f"DROP TRIGGER IF EXISTS zamid_guard_update ON {TABLE}",
        f"DROP TRIGGER IF EXISTS zamid_guard_delete ON {TABLE}",
        "DROP FUNCTION IF EXISTS zamid_guard()",
    ]


def _sqlite_drop():
    return ["DROP TRIGGER IF EXISTS zamid_guard_update", "DROP TRIGGER IF EXISTS zamid_guard_delete"]


def install(schema_editor, columns):
    vendor = schema_editor.connection.vendor
    statements = {"postgresql": _postgres, "sqlite": _sqlite}.get(vendor)
    if statements is None:
        raise NotImplementedError(f"ZAM ID triggers are not implemented for {vendor}")
    for sql in statements(columns):
        schema_editor.execute(sql)


def uninstall(schema_editor):
    vendor = schema_editor.connection.vendor
    for sql in {"postgresql": _postgres_drop, "sqlite": _sqlite_drop}[vendor]():
        schema_editor.execute(sql)
