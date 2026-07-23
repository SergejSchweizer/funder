from __future__ import annotations

from camovar.hosted_catalog import (
    HOSTED_ROLES,
    HOSTED_TABLES,
    apply_hosted_catalog_migrations,
    migration_plan,
    set_authenticated_user_sql,
    validate_hosted_catalog_contracts,
)


class FakeConnection:
    def __init__(self) -> None:
        self.executed: list[tuple[str, tuple[object, ...]]] = []

    def execute(self, sql: str, parameters: tuple[object, ...] = ()) -> object:
        self.executed.append((sql, parameters))
        return None


def test_hosted_catalog_contracts_validate_security_invariants() -> None:
    validate_hosted_catalog_contracts()

    roles_by_name = {role.name: role for role in HOSTED_ROLES}
    assert set(roles_by_name) == {
        "camovar_owner",
        "camovar_migrator",
        "camovar_app",
        "camovar_readonly",
    }
    assert not roles_by_name["camovar_app"].owns_tables
    assert all(not role.can_bypass_rls for role in HOSTED_ROLES)

    table_names = {table.name for table in HOSTED_TABLES}
    for required_table in (
        "camovar_app.users",
        "camovar_app.external_identities",
        "camovar_app.sessions",
        "camovar_app.provider_credentials",
        "camovar_app.projects",
        "camovar_app.download_runs",
        "camovar_app.market_objects",
        "camovar_app.dataset_snapshots",
        "camovar_app.user_grants",
        "camovar_app.selections",
        "camovar_app.analysis_runs",
        "camovar_app.artifacts",
        "camovar_app.artifact_inputs",
        "camovar_app.audit_events",
    ):
        assert required_table in table_names


def test_hosted_migration_sql_defines_rls_and_immutable_catalog_shape() -> None:
    migrations = migration_plan()
    sql = "\n".join(migration.sql.lower() for migration in migrations)

    assert [migration.version for migration in migrations] == [1, 2]
    assert len({migration.checksum for migration in migrations}) == len(migrations)
    assert "create table if not exists camovar_app.provider_credentials" in sql
    assert "ciphertext bytea not null" in sql
    assert "wrapped_data_key bytea not null" in sql
    assert "key_version text not null" in sql
    assert "create table if not exists camovar_app.market_objects" in sql
    assert "create table if not exists camovar_app.artifact_inputs" in sql
    assert "enable row level security" in sql
    assert "force row level security" in sql
    assert "camovar.current_user_id" in sql
    assert "revoke delete on all tables in schema camovar_app from camovar_app" in sql


def test_apply_hosted_catalog_migrations_is_deterministic_and_idempotent() -> None:
    connection = FakeConnection()

    apply_hosted_catalog_migrations(connection)

    role_statements = [
        statement for statement, _ in connection.executed if "create role" in statement
    ]
    migration_inserts = [
        parameters
        for statement, parameters in connection.executed
        if "insert into camovar_private.schema_migrations" in statement
    ]
    assert len(role_statements) == len(HOSTED_ROLES)
    assert len(migration_inserts) == len(migration_plan())
    assert migration_inserts == [
        (migration.version, migration.name, migration.checksum) for migration in migration_plan()
    ]


def test_authenticated_user_sql_uses_transaction_local_setting() -> None:
    sql, parameters = set_authenticated_user_sql("00000000-0000-0000-0000-000000000001")

    assert sql == "select set_config(%s, %s, true)"
    assert parameters == (
        "camovar.current_user_id",
        "00000000-0000-0000-0000-000000000001",
    )
