"""Encrypted hosted EODHD credential vault contracts."""

from __future__ import annotations

import hashlib
import hmac
import os
import uuid
from dataclasses import dataclass, replace

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


class CredentialVaultError(RuntimeError):
    """Raised when hosted credential handling fails closed."""


@dataclass(frozen=True)
class KeyEncryptionKey:
    """Versioned key-encryption key loaded from an external secret source."""

    version: str
    material: bytes

    def __post_init__(self) -> None:
        if not self.version:
            raise ValueError("key version is required")
        if len(self.material) not in {16, 24, 32}:
            raise ValueError("KEK material must be 128, 192, or 256 bits")


@dataclass(frozen=True)
class CredentialAssociatedData:
    """Associated data binding encrypted credentials to their owner and schema."""

    credential_id: str
    user_id: str
    provider: str = "eodhd"
    schema_version: int = 1

    def canonical(self) -> bytes:
        """Return stable associated data bytes for authenticated encryption."""

        return (
            f"credential_id={self.credential_id}|user_id={self.user_id}|"
            f"provider={self.provider}|schema_version={self.schema_version}"
        ).encode()


@dataclass(frozen=True)
class EncryptedCredentialRecord:
    """Persistable encrypted credential row without plaintext provider material."""

    credential_id: str
    user_id: str
    provider: str
    status: str
    ciphertext: bytes
    nonce: bytes
    wrapped_data_key: bytes
    wrap_nonce: bytes
    key_version: str
    associated_data: CredentialAssociatedData
    fingerprint_hmac: str
    masked_label: str


@dataclass(frozen=True)
class CredentialStatus:
    """Client-safe credential status response."""

    credential_id: str
    provider: str
    status: str
    key_version: str
    masked_label: str


class InMemoryCredentialStore:
    """Small in-memory credential repository used by tests and local adapters."""

    def __init__(self) -> None:
        self._records_by_user_provider: dict[tuple[str, str], EncryptedCredentialRecord] = {}

    def upsert(self, record: EncryptedCredentialRecord) -> None:
        """Store one logical active credential per user and provider."""

        self._records_by_user_provider[(record.user_id, record.provider)] = record

    def get(self, *, user_id: str, provider: str = "eodhd") -> EncryptedCredentialRecord | None:
        """Return the current logical credential record when present."""

        return self._records_by_user_provider.get((user_id, provider))


class EodhdCredentialVault:
    """Envelope-encrypted EODHD credential service."""

    def __init__(
        self,
        *,
        store: InMemoryCredentialStore,
        key_encryption_key: KeyEncryptionKey | None,
        fingerprint_secret: bytes,
    ) -> None:
        if not fingerprint_secret:
            raise ValueError("fingerprint_secret is required")
        self._store = store
        self._key_encryption_key = key_encryption_key
        self._fingerprint_secret = fingerprint_secret

    def set_credential(
        self,
        *,
        user_id: str,
        provider_key: str,
        credential_id: str | None = None,
    ) -> CredentialStatus:
        """Encrypt and store one active EODHD credential for a user."""

        if not provider_key:
            raise CredentialVaultError("provider key is required")
        key = self._require_kek()
        resolved_id = credential_id or str(uuid.uuid4())
        associated_data = CredentialAssociatedData(credential_id=resolved_id, user_id=user_id)
        data_key = AESGCM.generate_key(bit_length=256)
        data_nonce = os.urandom(12)
        wrap_nonce = os.urandom(12)
        ciphertext = AESGCM(data_key).encrypt(
            data_nonce,
            provider_key.encode("utf-8"),
            associated_data.canonical(),
        )
        wrapped_data_key = AESGCM(key.material).encrypt(
            wrap_nonce,
            data_key,
            associated_data.canonical(),
        )
        record = EncryptedCredentialRecord(
            credential_id=resolved_id,
            user_id=user_id,
            provider="eodhd",
            status="active",
            ciphertext=ciphertext,
            nonce=data_nonce,
            wrapped_data_key=wrapped_data_key,
            wrap_nonce=wrap_nonce,
            key_version=key.version,
            associated_data=associated_data,
            fingerprint_hmac=_credential_fingerprint(
                secret=self._fingerprint_secret,
                provider_key=provider_key,
            ),
            masked_label=mask_provider_key(provider_key),
        )
        self._store.upsert(record)
        return self.status(user_id=user_id)

    def unwrap_for_provider_call(self, *, user_id: str) -> str:
        """Decrypt a credential immediately before a provider request."""

        record = self._require_record(user_id=user_id)
        if record.status != "active":
            raise CredentialVaultError("credential is not active")
        if record.associated_data.user_id != user_id:
            raise CredentialVaultError("credential owner mismatch")
        key = self._require_kek()
        if key.version != record.key_version:
            raise CredentialVaultError("credential key version is unavailable")
        try:
            data_key = AESGCM(key.material).decrypt(
                record.wrap_nonce,
                record.wrapped_data_key,
                record.associated_data.canonical(),
            )
            plaintext = AESGCM(data_key).decrypt(
                record.nonce,
                record.ciphertext,
                record.associated_data.canonical(),
            )
        except InvalidTag as error:
            raise CredentialVaultError("credential authentication failed") from error
        return plaintext.decode("utf-8")

    def status(self, *, user_id: str) -> CredentialStatus:
        """Return client-safe credential status metadata."""

        record = self._require_record(user_id=user_id)
        return CredentialStatus(
            credential_id=record.credential_id,
            provider=record.provider,
            status=record.status,
            key_version=record.key_version,
            masked_label=record.masked_label,
        )

    def revoke(self, *, user_id: str) -> CredentialStatus:
        """Mark the current credential revoked."""

        record = self._require_record(user_id=user_id)
        updated = replace(record, status="revoked")
        self._store.upsert(updated)
        return self.status(user_id=user_id)

    def delete(self, *, user_id: str) -> CredentialStatus:
        """Mark the current credential deleted without exposing plaintext."""

        record = self._require_record(user_id=user_id)
        updated = replace(record, status="deleted")
        self._store.upsert(updated)
        return self.status(user_id=user_id)

    def rotate_key(
        self,
        *,
        user_id: str,
        new_key_encryption_key: KeyEncryptionKey,
    ) -> CredentialStatus:
        """Rewrap an active credential under a new KEK without provider-key re-entry."""

        plaintext = self.unwrap_for_provider_call(user_id=user_id)
        original = self._require_record(user_id=user_id)
        self._key_encryption_key = new_key_encryption_key
        return self.set_credential(
            user_id=user_id,
            provider_key=plaintext,
            credential_id=original.credential_id,
        )

    def _require_record(self, *, user_id: str) -> EncryptedCredentialRecord:
        record = self._store.get(user_id=user_id)
        if record is None:
            raise CredentialVaultError("credential not found")
        return record

    def _require_kek(self) -> KeyEncryptionKey:
        if self._key_encryption_key is None:
            raise CredentialVaultError("key-encryption key is unavailable")
        return self._key_encryption_key


def mask_provider_key(provider_key: str) -> str:
    """Return a non-secret label for a provider key."""

    if len(provider_key) <= 8:
        return "<redacted>"
    return f"{provider_key[:4]}...{provider_key[-4:]}"


def redact_credential_text(text: str, *, provider_key: str) -> str:
    """Redact provider-key occurrences from logs or exceptions."""

    return text.replace(provider_key, "<redacted>")


def _credential_fingerprint(*, secret: bytes, provider_key: str) -> str:
    return hmac.new(secret, provider_key.encode("utf-8"), hashlib.sha256).hexdigest()
