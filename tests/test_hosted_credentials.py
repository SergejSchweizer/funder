from __future__ import annotations

import pytest

from camovar.hosted_credentials import (
    CredentialVaultError,
    EodhdCredentialVault,
    InMemoryCredentialStore,
    KeyEncryptionKey,
    mask_provider_key,
    redact_credential_text,
)


def _vault(
    key: KeyEncryptionKey | None = None,
) -> tuple[EodhdCredentialVault, InMemoryCredentialStore]:
    store = InMemoryCredentialStore()
    vault = EodhdCredentialVault(
        store=store,
        key_encryption_key=key or KeyEncryptionKey(version="kek-v1", material=b"1" * 32),
        fingerprint_secret=b"fingerprint-secret",
    )
    return vault, store


def test_eodhd_credential_encrypts_decrypts_and_returns_masked_status() -> None:
    vault, store = _vault()

    status = vault.set_credential(user_id="user-1", provider_key="abcd-secret-token-1234")

    assert status.status == "active"
    assert status.masked_label == "abcd...1234"
    assert vault.unwrap_for_provider_call(user_id="user-1") == "abcd-secret-token-1234"
    record = store.get(user_id="user-1")
    assert record is not None
    assert b"abcd-secret-token-1234" not in record.ciphertext
    assert b"abcd-secret-token-1234" not in record.wrapped_data_key


def test_wrong_user_associated_data_rejects_decryption() -> None:
    vault, store = _vault()
    vault.set_credential(user_id="user-1", provider_key="abcd-secret-token-1234")
    record = store.get(user_id="user-1")
    assert record is not None
    store.upsert(record.__class__(**{**record.__dict__, "user_id": "user-2"}))

    with pytest.raises(CredentialVaultError, match="owner mismatch|authentication failed"):
        vault.unwrap_for_provider_call(user_id="user-2")


def test_tampering_and_wrong_key_fail_closed() -> None:
    vault, store = _vault()
    vault.set_credential(user_id="user-1", provider_key="abcd-secret-token-1234")
    record = store.get(user_id="user-1")
    assert record is not None
    tampered_byte = bytes([record.ciphertext[-1] ^ 1])
    store.upsert(
        record.__class__(
            **{**record.__dict__, "ciphertext": record.ciphertext[:-1] + tampered_byte}
        )
    )

    with pytest.raises(CredentialVaultError, match="authentication failed"):
        vault.unwrap_for_provider_call(user_id="user-1")

    unavailable_key_vault = EodhdCredentialVault(
        store=store,
        key_encryption_key=KeyEncryptionKey(version="other", material=b"2" * 32),
        fingerprint_secret=b"fingerprint-secret",
    )
    with pytest.raises(CredentialVaultError, match="key version"):
        unavailable_key_vault.unwrap_for_provider_call(user_id="user-1")


def test_replacement_revocation_deletion_and_missing_kek() -> None:
    vault, _ = _vault()
    first = vault.set_credential(user_id="user-1", provider_key="abcd-secret-token-1234")
    second = vault.set_credential(user_id="user-1", provider_key="wxyz-secret-token-9999")

    assert second.credential_id != first.credential_id
    assert vault.unwrap_for_provider_call(user_id="user-1") == "wxyz-secret-token-9999"
    assert vault.revoke(user_id="user-1").status == "revoked"
    with pytest.raises(CredentialVaultError, match="not active"):
        vault.unwrap_for_provider_call(user_id="user-1")
    assert vault.delete(user_id="user-1").status == "deleted"

    missing_kek, _ = _vault(key=None)
    missing_kek._key_encryption_key = None  # noqa: SLF001
    with pytest.raises(CredentialVaultError, match="unavailable"):
        missing_kek.set_credential(user_id="user-1", provider_key="abcd-secret-token-1234")


def test_key_rotation_without_provider_key_reentry_preserves_logical_credential() -> None:
    vault, _ = _vault()
    first = vault.set_credential(user_id="user-1", provider_key="abcd-secret-token-1234")

    rotated = vault.rotate_key(
        user_id="user-1",
        new_key_encryption_key=KeyEncryptionKey(version="kek-v2", material=b"2" * 32),
    )

    assert rotated.credential_id == first.credential_id
    assert rotated.key_version == "kek-v2"
    assert vault.unwrap_for_provider_call(user_id="user-1") == "abcd-secret-token-1234"


def test_redaction_and_short_masking_do_not_expose_secret() -> None:
    assert mask_provider_key("short") == "<redacted>"
    assert (
        redact_credential_text(
            "provider failed for abcd-secret-token-1234",
            provider_key="abcd-secret-token-1234",
        )
        == "provider failed for <redacted>"
    )
