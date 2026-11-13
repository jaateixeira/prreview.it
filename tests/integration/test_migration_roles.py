"""Migration 0009 turns preset roles into the three fixed roles and back (ADR 0017)."""

from sqlalchemy import create_engine, text

from previewit.adapters.persistence.migrate import downgrade, upgrade


def _roles(engine, table: str, key: str = "user_id") -> dict[str, str]:
    with engine.connect() as conn:
        return {r[0]: r[1] for r in conn.execute(text(f"SELECT {key}, roles FROM {table}"))}


def test_preset_roles_become_fixed_roles_and_back(tmp_path):
    url = f"sqlite:///{tmp_path / 'm.db'}"
    upgrade(url, "0008")
    engine = create_engine(url)
    with engine.begin() as conn:
        for uid in ("t", "a", "s", "x"):
            conn.execute(
                text(
                    "INSERT INTO users (id, display_name, email_verified, created_at) "
                    "VALUES (:id, :id, 0, '2026-01-01')"
                ),
                {"id": uid},
            )
        conn.execute(
            text(
                "INSERT INTO organizations (id, name, preset_key, created_at) "
                "VALUES ('o','O','education','2026-01-01')"
            )
        )
        conn.execute(
            text(
                "INSERT INTO spaces (id, org_id, name, created_at) "
                "VALUES ('s1','o','S','2026-01-01')"
            )
        )
        for uid, role in (("t", "teacher"), ("a", "assistant"), ("s", "student"), ("x", "custom")):
            conn.execute(
                text(
                    "INSERT INTO space_members (space_id, user_id, org_id, role_key) "
                    "VALUES ('s1', :u, 'o', :r)"
                ),
                {"u": uid, "r": role},
            )
        conn.execute(
            text(
                "INSERT INTO invites (id, org_id, space_id, role_key, created_by, expires_at, "
                "max_uses, uses, revoked) "
                "VALUES ('i1','o','s1','student','t','2030-01-01',NULL,0,0)"
            )
        )

    upgrade(url)
    assert _roles(engine, "space_members") == {
        "t": "organizer",
        "a": "organizer",
        "s": "author,reviewer",
        "x": "reviewer",  # unknown role: least privilege
    }
    assert _roles(engine, "invites", "id") == {"i1": "author,reviewer"}

    downgrade(url, "0008")
    with engine.connect() as conn:
        back = {
            r[0]: r[1] for r in conn.execute(text("SELECT user_id, role_key FROM space_members"))
        }
    assert back == {"t": "teacher", "a": "teacher", "s": "student", "x": "student"}


def test_existing_calls_become_protected_and_the_column_can_be_dropped(tmp_path):
    url = f"sqlite:///{tmp_path / 'c.db'}"
    upgrade(url, "0009")
    engine = create_engine(url)
    day = "2026-01-01"
    rows = [
        ("users", "id, display_name, email_verified, created_at", "'u', 'u', 0, :d"),
        ("organizations", "id, name, preset_key, created_at", "'o', 'O', 'education', :d"),
        ("spaces", "id, org_id, name, created_at", "'s', 'o', 'S', :d"),
        (
            "calls",
            "id, org_id, space_id, title, description, artifact_type, group_work, published, "
            "created_by, created_at",
            "'c', 'o', 's', 'T', '', 'text', 0, 1, 'u', :d",
        ),
    ]
    with engine.begin() as conn:
        for table, columns, values in rows:
            conn.execute(text(f"INSERT INTO {table} ({columns}) VALUES ({values})"), {"d": day})
    upgrade(url)
    with engine.connect() as conn:
        assert conn.execute(text("SELECT access FROM calls")).scalar_one() == "protected"
    downgrade(url, "0009")
    with engine.connect() as conn:
        assert conn.execute(text("SELECT title FROM calls")).scalar_one() == "T"
