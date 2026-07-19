from __future__ import annotations

from dataclasses import replace

import pytest

from founder.hosted_auth import (
    GoogleIdTokenClaims,
    GoogleOidcAuthService,
    HostedAuthError,
    InMemoryGoogleIdentityStore,
    OidcClientConfig,
    OidcTokenResponse,
    ServerSessionStore,
)


class SequenceTokens:
    def __init__(self) -> None:
        self._counter = 0

    def __call__(self) -> str:
        self._counter += 1
        return f"token-{self._counter:04d}"


class MutableClock:
    def __init__(self, now: int = 1_000) -> None:
        self.now = now

    def __call__(self) -> int:
        return self.now


class FakeTokenExchanger:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str]] = []

    def exchange_code(
        self,
        *,
        code: str,
        code_verifier: str,
        redirect_uri: str,
    ) -> OidcTokenResponse:
        self.calls.append((code, code_verifier, redirect_uri))
        return OidcTokenResponse(id_token=f"id-token:{code}")


class FakeVerifier:
    def __init__(self, claims: GoogleIdTokenClaims) -> None:
        self.claims = claims
        self.calls: list[tuple[str, str, str, int]] = []

    def verify(
        self,
        *,
        id_token: str,
        expected_audience: str,
        expected_nonce: str,
        now_epoch_seconds: int,
    ) -> GoogleIdTokenClaims:
        self.calls.append((id_token, expected_audience, expected_nonce, now_epoch_seconds))
        if self.claims.nonce == "<expected>":
            return replace(self.claims, nonce=expected_nonce)
        return self.claims


def _claims(**overrides: object) -> GoogleIdTokenClaims:
    values: dict[str, object] = {
        "issuer": "https://accounts.google.com",
        "audience": "founder-client",
        "subject": "google-subject-1",
        "email": "first@example.com",
        "email_verified": True,
        "expires_at_epoch_seconds": 2_000,
        "nonce": "<expected>",
        "display_name": "First User",
        "hosted_domain": "",
    }
    values.update(overrides)
    return GoogleIdTokenClaims(**values)  # type: ignore[arg-type]


def _service(
    *,
    claims: GoogleIdTokenClaims | None = None,
    allowed_domains: tuple[str, ...] = (),
    clock: MutableClock | None = None,
    identity_store: InMemoryGoogleIdentityStore | None = None,
) -> tuple[
    GoogleOidcAuthService,
    FakeTokenExchanger,
    InMemoryGoogleIdentityStore,
    ServerSessionStore,
    MutableClock,
]:
    token_factory = SequenceTokens()
    mutable_clock = MutableClock() if clock is None else clock
    resolved_identity_store = (
        InMemoryGoogleIdentityStore() if identity_store is None else identity_store
    )
    session_store = ServerSessionStore(hmac_secret="session-secret", token_factory=token_factory)
    exchanger = FakeTokenExchanger()
    verifier = FakeVerifier(_claims() if claims is None else claims)
    service = GoogleOidcAuthService(
        config=OidcClientConfig(
            client_id="founder-client",
            client_secret_ref="/run/secrets/google-client-secret",
            redirect_uri="https://founder.example.test/auth/google/callback",
            allowed_domains=allowed_domains,
            state_ttl_seconds=60,
            session_ttl_seconds=120,
        ),
        token_exchanger=exchanger,
        id_token_verifier=verifier,
        identity_store=resolved_identity_store,
        session_store=session_store,
        token_factory=token_factory,
        clock=mutable_clock,
    )
    return service, exchanger, resolved_identity_store, session_store, mutable_clock


def test_google_oidc_first_login_creates_empty_user_session() -> None:
    service, exchanger, identity_store, session_store, clock = _service()

    request = service.begin_login()
    session = service.complete_callback(code="auth-code", state=request.state)

    assert "code_challenge_method=S256" in request.authorization_url
    assert "client_id=founder-client" in request.authorization_url
    assert exchanger.calls == [
        (
            "auth-code",
            request.code_verifier,
            "https://founder.example.test/auth/google/callback",
        )
    ]
    assert identity_store.user_count() == 1
    assert (
        session_store.require_session(
            session_token=session.session_token,
            csrf_token=session.csrf_token,
            now_epoch_seconds=clock.now,
        )
        == session.user_id
    )


def test_repeat_login_uses_google_subject_even_when_email_changes() -> None:
    service, _, identity_store, _, _ = _service()

    first_request = service.begin_login()
    first_session = service.complete_callback(code="first-code", state=first_request.state)

    service_with_same_store, _, _, _, _ = _service(
        claims=_claims(email="changed@example.com", display_name="Changed"),
        identity_store=identity_store,
    )
    second_request = service_with_same_store.begin_login()
    second_session = service_with_same_store.complete_callback(
        code="second-code",
        state=second_request.state,
    )

    assert first_session.user_id == second_session.user_id
    assert identity_store.user_count() == 1


@pytest.mark.parametrize(
    ("claim_override", "error_match"),
    (
        ({"issuer": "https://evil.example"}, "issuer"),
        ({"audience": "other-client"}, "audience"),
        ({"nonce": "wrong-nonce"}, "nonce"),
        ({"email_verified": False}, "verified"),
        ({"expires_at_epoch_seconds": 999}, "expired"),
        ({"subject": ""}, "subject"),
    ),
)
def test_google_callback_rejects_invalid_verified_claims(
    claim_override: dict[str, object],
    error_match: str,
) -> None:
    service, _, _, _, _ = _service(claims=_claims(**claim_override))

    request = service.begin_login()

    with pytest.raises(HostedAuthError, match=error_match):
        service.complete_callback(code="auth-code", state=request.state)


def test_google_callback_rejects_replayed_unknown_and_expired_state() -> None:
    service, _, _, _, clock = _service()

    request = service.begin_login()
    service.complete_callback(code="auth-code", state=request.state)
    with pytest.raises(HostedAuthError, match="already consumed"):
        service.complete_callback(code="auth-code", state=request.state)
    with pytest.raises(HostedAuthError, match="unknown"):
        service.complete_callback(code="auth-code", state="not-issued")

    expired_request = service.begin_login()
    clock.now = expired_request.expires_at_epoch_seconds
    with pytest.raises(HostedAuthError, match="expired"):
        service.complete_callback(code="auth-code", state=expired_request.state)


def test_session_expiry_revocation_csrf_and_rotation_are_enforced() -> None:
    session_store = ServerSessionStore(
        hmac_secret="session-secret",
        token_factory=SequenceTokens(),
    )
    session = session_store.create_session(
        user_id="user-1",
        now_epoch_seconds=100,
        ttl_seconds=10,
    )

    assert (
        session_store.require_session(
            session_token=session.session_token,
            csrf_token=session.csrf_token,
            now_epoch_seconds=109,
        )
        == "user-1"
    )
    with pytest.raises(HostedAuthError, match="csrf"):
        session_store.require_session(
            session_token=session.session_token,
            csrf_token="wrong",
            now_epoch_seconds=109,
        )
    with pytest.raises(HostedAuthError, match="expired"):
        session_store.require_session(
            session_token=session.session_token,
            csrf_token=session.csrf_token,
            now_epoch_seconds=110,
        )

    rotated = session_store.rotate_session(
        session_token=session.session_token,
        user_id="user-1",
        now_epoch_seconds=111,
        ttl_seconds=10,
    )
    with pytest.raises(HostedAuthError, match="revoked"):
        session_store.require_session(
            session_token=session.session_token,
            csrf_token=session.csrf_token,
            now_epoch_seconds=112,
        )
    assert (
        session_store.require_session(
            session_token=rotated.session_token,
            csrf_token=rotated.csrf_token,
            now_epoch_seconds=112,
        )
        == "user-1"
    )


def test_google_domain_allowlist_is_disabled_by_default_and_enforced_when_configured() -> None:
    service, _, _, _, _ = _service(claims=_claims(hosted_domain="other.example"))
    request = service.begin_login()
    service.complete_callback(code="auth-code", state=request.state)

    restricted_service, _, _, _, _ = _service(
        claims=_claims(hosted_domain="other.example"),
        allowed_domains=("allowed.example",),
    )
    restricted_request = restricted_service.begin_login()
    with pytest.raises(HostedAuthError, match="domain"):
        restricted_service.complete_callback(code="auth-code", state=restricted_request.state)


def test_concurrent_sessions_for_same_user_remain_independent() -> None:
    service, _, _, session_store, clock = _service()

    first_request = service.begin_login()
    first_session = service.complete_callback(code="first-code", state=first_request.state)
    second_request = service.begin_login()
    second_session = service.complete_callback(code="second-code", state=second_request.state)

    assert first_session.user_id == second_session.user_id
    session_store.revoke_session(first_session.session_token)
    with pytest.raises(HostedAuthError, match="revoked"):
        session_store.require_session(
            session_token=first_session.session_token,
            csrf_token=first_session.csrf_token,
            now_epoch_seconds=clock.now,
        )
    assert (
        session_store.require_session(
            session_token=second_session.session_token,
            csrf_token=second_session.csrf_token,
            now_epoch_seconds=clock.now,
        )
        == second_session.user_id
    )
