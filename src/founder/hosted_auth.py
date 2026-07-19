"""Google OIDC and server-side session contracts for hosted Founder."""

from __future__ import annotations

import base64
import hashlib
import hmac
import time
import urllib.parse
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol


class HostedAuthError(RuntimeError):
    """Raised when hosted authentication fails closed."""


class TokenExchanger(Protocol):
    """OIDC authorization-code token exchange boundary."""

    def exchange_code(
        self,
        *,
        code: str,
        code_verifier: str,
        redirect_uri: str,
    ) -> OidcTokenResponse:
        """Exchange an authorization code for provider tokens.

        Args:
            code: Authorization code returned by Google.
            code_verifier: PKCE verifier stored server-side for this login attempt.
            redirect_uri: Strictly configured redirect URI.

        Returns:
            Token response containing the ID token to verify.
        """
        ...


class IdTokenVerifier(Protocol):
    """Google ID-token signature and claim verification boundary."""

    def verify(
        self,
        *,
        id_token: str,
        expected_audience: str,
        expected_nonce: str,
        now_epoch_seconds: int,
    ) -> GoogleIdTokenClaims:
        """Verify a Google ID token.

        Args:
            id_token: Raw ID token from the token exchange.
            expected_audience: Configured Google client id.
            expected_nonce: Nonce bound to the login attempt.
            now_epoch_seconds: Current epoch seconds for expiry validation.

        Returns:
            Verified Google claims.
        """
        ...


@dataclass(frozen=True)
class OidcClientConfig:
    """Hosted Google OIDC client configuration.

    Args:
        client_id: Google OAuth client id.
        client_secret_ref: Runtime secret reference, not the secret value.
        redirect_uri: Exact callback URI registered with Google.
        auth_endpoint: Google authorization endpoint.
        scopes: Requested OIDC scopes.
        allowed_domains: Optional hosted-domain allowlist.
        state_ttl_seconds: Login state lifetime.
        session_ttl_seconds: Server-side session lifetime.
    """

    client_id: str
    client_secret_ref: str
    redirect_uri: str
    auth_endpoint: str = "https://accounts.google.com/o/oauth2/v2/auth"
    scopes: tuple[str, ...] = ("openid", "email", "profile")
    allowed_domains: tuple[str, ...] = ()
    state_ttl_seconds: int = 600
    session_ttl_seconds: int = 3600

    def __post_init__(self) -> None:
        if not self.client_id:
            raise ValueError("client_id is required")
        if not self.client_secret_ref:
            raise ValueError("client_secret_ref is required")
        if not self.redirect_uri.startswith("https://"):
            raise ValueError("redirect_uri must be an https URL")
        if self.state_ttl_seconds <= 0:
            raise ValueError("state_ttl_seconds must be positive")
        if self.session_ttl_seconds <= 0:
            raise ValueError("session_ttl_seconds must be positive")


@dataclass(frozen=True)
class OidcAuthRequest:
    """Server-side login request state returned to the web layer."""

    authorization_url: str
    state: str
    nonce: str
    code_verifier: str
    code_challenge: str
    expires_at_epoch_seconds: int


@dataclass(frozen=True)
class OidcTokenResponse:
    """Minimal token response consumed by hosted auth."""

    id_token: str


@dataclass(frozen=True)
class GoogleIdTokenClaims:
    """Verified Google ID-token claims.

    Args:
        issuer: Token issuer.
        audience: Token audience.
        subject: Stable Google subject claim.
        email: Current Google email address.
        email_verified: Whether Google verified the email.
        expires_at_epoch_seconds: Token expiry.
        nonce: Login nonce.
        display_name: Optional profile name.
        hosted_domain: Optional Google Workspace hosted domain.
    """

    issuer: str
    audience: str
    subject: str
    email: str
    email_verified: bool
    expires_at_epoch_seconds: int
    nonce: str
    display_name: str = ""
    hosted_domain: str = ""


@dataclass(frozen=True)
class HostedUser:
    """Hosted authenticated user identity."""

    user_id: str
    google_subject: str
    email: str
    display_name: str


@dataclass(frozen=True)
class HostedSession:
    """Opaque server-side session issued to the browser as cookies."""

    session_token: str
    csrf_token: str
    user_id: str
    expires_at_epoch_seconds: int


@dataclass
class _PendingState:
    state_hash: str
    nonce: str
    code_verifier: str
    expires_at_epoch_seconds: int
    consumed: bool = False


@dataclass
class _StoredSession:
    session_hash: str
    csrf_hash: str
    user_id: str
    expires_at_epoch_seconds: int
    revoked: bool = False


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _base64url_digest(value: str) -> str:
    digest = hashlib.sha256(value.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def _default_token_factory() -> str:
    return uuid.uuid4().hex + uuid.uuid4().hex


class InMemoryGoogleIdentityStore:
    """Deterministic in-memory Google identity repository for tests and local adapters."""

    def __init__(self) -> None:
        self._users_by_subject: dict[str, HostedUser] = {}

    def resolve_google_identity(self, claims: GoogleIdTokenClaims) -> HostedUser:
        """Create or update one user for a stable Google subject.

        Args:
            claims: Verified Google ID-token claims.

        Returns:
            Existing or newly created hosted user.
        """

        existing = self._users_by_subject.get(claims.subject)
        user_id = (
            existing.user_id
            if existing is not None
            else str(uuid.uuid5(uuid.NAMESPACE_URL, claims.subject))
        )
        user = HostedUser(
            user_id=user_id,
            google_subject=claims.subject,
            email=claims.email,
            display_name=claims.display_name,
        )
        self._users_by_subject[claims.subject] = user
        return user

    def user_count(self) -> int:
        """Return number of logical hosted users.

        Returns:
            Count of unique Google subjects resolved.
        """

        return len(self._users_by_subject)


class ServerSessionStore:
    """Server-side opaque session and CSRF store."""

    def __init__(
        self,
        *,
        hmac_secret: str,
        token_factory: Callable[[], str] = _default_token_factory,
    ) -> None:
        if not hmac_secret:
            raise ValueError("hmac_secret is required")
        self._hmac_secret = hmac_secret
        self._token_factory = token_factory
        self._sessions_by_hash: dict[str, _StoredSession] = {}

    def create_session(
        self,
        *,
        user_id: str,
        now_epoch_seconds: int,
        ttl_seconds: int,
    ) -> HostedSession:
        """Create a short-lived server-side session.

        Args:
            user_id: Authenticated internal user id.
            now_epoch_seconds: Current epoch seconds.
            ttl_seconds: Session lifetime.

        Returns:
            Opaque session and CSRF tokens to send as secure cookies.
        """

        session_token = self._new_token()
        csrf_token = self._new_token()
        session_hash = self._hmac_token(session_token)
        stored = _StoredSession(
            session_hash=session_hash,
            csrf_hash=self._hmac_token(csrf_token),
            user_id=user_id,
            expires_at_epoch_seconds=now_epoch_seconds + ttl_seconds,
        )
        self._sessions_by_hash[session_hash] = stored
        return HostedSession(
            session_token=session_token,
            csrf_token=csrf_token,
            user_id=user_id,
            expires_at_epoch_seconds=stored.expires_at_epoch_seconds,
        )

    def require_session(
        self,
        *,
        session_token: str,
        csrf_token: str,
        now_epoch_seconds: int,
    ) -> str:
        """Validate an active session and matching CSRF token.

        Args:
            session_token: Opaque session cookie value.
            csrf_token: Opaque CSRF cookie or submitted token.
            now_epoch_seconds: Current epoch seconds.

        Returns:
            Authenticated user id.

        Raises:
            HostedAuthError: If the session is absent, expired, revoked, or CSRF-invalid.
        """

        stored = self._sessions_by_hash.get(self._hmac_token(session_token))
        if stored is None:
            raise HostedAuthError("session not found")
        if stored.revoked:
            raise HostedAuthError("session revoked")
        if now_epoch_seconds >= stored.expires_at_epoch_seconds:
            raise HostedAuthError("session expired")
        if not hmac.compare_digest(stored.csrf_hash, self._hmac_token(csrf_token)):
            raise HostedAuthError("csrf validation failed")
        return stored.user_id

    def revoke_session(self, session_token: str) -> None:
        """Revoke one session.

        Args:
            session_token: Opaque session cookie value.

        Side Effects:
            Marks the session as revoked when it exists.
        """

        stored = self._sessions_by_hash.get(self._hmac_token(session_token))
        if stored is not None:
            stored.revoked = True

    def rotate_session(
        self,
        *,
        session_token: str,
        user_id: str,
        now_epoch_seconds: int,
        ttl_seconds: int,
    ) -> HostedSession:
        """Revoke the current session and issue a replacement.

        Args:
            session_token: Current session token.
            user_id: Authenticated user id to bind to the replacement session.
            now_epoch_seconds: Current epoch seconds.
            ttl_seconds: Session lifetime.

        Returns:
            Replacement hosted session.
        """

        self.revoke_session(session_token)
        return self.create_session(
            user_id=user_id,
            now_epoch_seconds=now_epoch_seconds,
            ttl_seconds=ttl_seconds,
        )

    def _new_token(self) -> str:
        token = self._token_factory()
        if token:
            return token
        raise HostedAuthError("token factory returned invalid token")

    def _hmac_token(self, token: str) -> str:
        return hmac.new(
            self._hmac_secret.encode("utf-8"),
            token.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()


class GoogleOidcAuthService:
    """Google-only OIDC authorization-code flow with PKCE and server sessions."""

    def __init__(
        self,
        *,
        config: OidcClientConfig,
        token_exchanger: TokenExchanger,
        id_token_verifier: IdTokenVerifier,
        identity_store: InMemoryGoogleIdentityStore,
        session_store: ServerSessionStore,
        token_factory: Callable[[], str] = _default_token_factory,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._config = config
        self._token_exchanger = token_exchanger
        self._id_token_verifier = id_token_verifier
        self._identity_store = identity_store
        self._session_store = session_store
        self._token_factory = token_factory
        self._clock = clock
        self._pending_by_state_hash: dict[str, _PendingState] = {}

    def begin_login(self) -> OidcAuthRequest:
        """Create a Google authorization request.

        Returns:
            OIDC request containing redirect URL and server-bound PKCE/nonce state.
        """

        state = self._new_token()
        nonce = self._new_token()
        code_verifier = self._new_token()
        code_challenge = _base64url_digest(code_verifier)
        expires_at = self._now() + self._config.state_ttl_seconds
        pending = _PendingState(
            state_hash=_sha256(state),
            nonce=nonce,
            code_verifier=code_verifier,
            expires_at_epoch_seconds=expires_at,
        )
        self._pending_by_state_hash[pending.state_hash] = pending
        query = urllib.parse.urlencode(
            {
                "client_id": self._config.client_id,
                "redirect_uri": self._config.redirect_uri,
                "response_type": "code",
                "scope": " ".join(self._config.scopes),
                "state": state,
                "nonce": nonce,
                "code_challenge": code_challenge,
                "code_challenge_method": "S256",
            }
        )
        return OidcAuthRequest(
            authorization_url=f"{self._config.auth_endpoint}?{query}",
            state=state,
            nonce=nonce,
            code_verifier=code_verifier,
            code_challenge=code_challenge,
            expires_at_epoch_seconds=expires_at,
        )

    def complete_callback(self, *, code: str, state: str) -> HostedSession:
        """Validate a Google callback and create a hosted session.

        Args:
            code: Authorization code from Google.
            state: Opaque state returned by the browser.

        Returns:
            Hosted server-side session.

        Raises:
            HostedAuthError: If state, token claims, domain, or session creation fail.
        """

        now_epoch_seconds = self._now()
        pending = self._pending_by_state_hash.get(_sha256(state))
        if pending is None:
            raise HostedAuthError("unknown oidc state")
        if pending.consumed:
            raise HostedAuthError("oidc state already consumed")
        if now_epoch_seconds >= pending.expires_at_epoch_seconds:
            raise HostedAuthError("oidc state expired")
        pending.consumed = True

        token_response = self._token_exchanger.exchange_code(
            code=code,
            code_verifier=pending.code_verifier,
            redirect_uri=self._config.redirect_uri,
        )
        claims = self._id_token_verifier.verify(
            id_token=token_response.id_token,
            expected_audience=self._config.client_id,
            expected_nonce=pending.nonce,
            now_epoch_seconds=now_epoch_seconds,
        )
        self._validate_claims(claims, pending)
        user = self._identity_store.resolve_google_identity(claims)
        return self._session_store.create_session(
            user_id=user.user_id,
            now_epoch_seconds=now_epoch_seconds,
            ttl_seconds=self._config.session_ttl_seconds,
        )

    def _validate_claims(self, claims: GoogleIdTokenClaims, pending: _PendingState) -> None:
        if claims.issuer not in {"https://accounts.google.com", "accounts.google.com"}:
            raise HostedAuthError("invalid google issuer")
        if claims.audience != self._config.client_id:
            raise HostedAuthError("invalid google audience")
        if not claims.subject:
            raise HostedAuthError("missing google subject")
        if claims.nonce != pending.nonce:
            raise HostedAuthError("invalid oidc nonce")
        if self._now() >= claims.expires_at_epoch_seconds:
            raise HostedAuthError("id token expired")
        if not claims.email_verified:
            raise HostedAuthError("google email is not verified")
        if (
            self._config.allowed_domains
            and claims.hosted_domain not in self._config.allowed_domains
        ):
            raise HostedAuthError("google hosted domain is not allowed")

    def _new_token(self) -> str:
        token = self._token_factory()
        if token:
            return token
        raise HostedAuthError("token factory returned invalid token")

    def _now(self) -> int:
        return int(self._clock())
