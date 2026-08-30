"""Authentication for the Operations API.

Ships a pluggable :class:`Authenticator` protocol plus two implementations:

* :class:`StaticTokenAuthenticator` — maps bearer tokens to principals from a
  configured table. Intended for local development and tests.
* :class:`HeaderPrincipalAuthenticator` — trusts principal identity asserted by
  an upstream gateway (App Service Easy Auth, API Management, an ingress that
  has already validated the Entra ID token). This is the production posture:
  AIOps does not re-implement OIDC, it consumes a verified assertion.

Token validation against Entra ID directly is deliberately *not* implemented
here; wiring a JWKS-validating authenticator is a drop-in replacement for the
protocol below.
"""

from __future__ import annotations

import hmac
import secrets
from collections.abc import Callable, Mapping
from typing import Protocol

from .errors import ApiError, ErrorCode
from .rbac import Grant, Principal


class Authenticator(Protocol):
    """Resolves request headers into an authenticated principal."""

    def authenticate(self, headers: Mapping[str, str]) -> Principal: ...


def _bearer_token(headers: Mapping[str, str]) -> str:
    raw = headers.get("authorization") or headers.get("Authorization") or ""
    prefix, _, token = str(raw).partition(" ")
    if prefix.strip().casefold() != "bearer" or not token.strip():
        # Deliberately no header contents logged (a malformed value could
        # still carry a fragment of a secret). This print is the only trace
        # of "no bearer token" 401s -- without it, this rejection path is
        # indistinguishable in logs from the JWT-invalid and grant-denied
        # paths, which made a prior production incident (browser calls
        # 401-ing in a burst then self-recovering) unresolvable from logs.
        print(f"bearer_token_missing has_authorization={bool(raw)!r}")
        raise ApiError(ErrorCode.UNAUTHENTICATED, "A bearer token is required")
    return token.strip()


class StaticTokenAuthenticator:
    """Bearer tokens mapped to principals from an in-memory table.

    Comparison is constant-time so the API does not leak token contents through
    response timing.
    """

    def __init__(self, tokens: Mapping[str, Principal]) -> None:
        if not tokens:
            raise ValueError("At least one token must be configured")
        self._tokens: dict[str, Principal] = {}
        for token, principal in tokens.items():
            value = str(token or "").strip()
            if len(value) < 16:
                raise ValueError(
                    "API tokens must be at least 16 characters to resist guessing"
                )
            if not isinstance(principal, Principal):
                raise TypeError("Token table values must be Principal instances")
            self._tokens[value] = principal

    def authenticate(self, headers: Mapping[str, str]) -> Principal:
        presented = _bearer_token(headers)
        for token, principal in self._tokens.items():
            if hmac.compare_digest(token, presented):
                return principal
        raise ApiError(ErrorCode.UNAUTHENTICATED, "Bearer token is not recognized")


class HeaderPrincipalAuthenticator:
    """Consumes a principal assertion from a trusted upstream gateway.

    The gateway is responsible for validating the Entra ID token; this reads the
    resulting identity headers. Because these headers are trusted implicitly,
    this authenticator must only ever be reachable behind that gateway.
    """

    def __init__(
        self,
        *,
        subject_header: str = "x-ms-client-principal-name",
        roles_header: str = "x-ms-client-principal-roles",
        assertion_header: str = "x-aiops-gateway-assertion",
        assertion_value: str = "",
        grants_resolver: Callable[[str, list[str]], tuple[Grant, ...]] | None = None,
    ) -> None:
        self.subject_header = subject_header.casefold()
        self.roles_header = roles_header.casefold()
        self.assertion_header = assertion_header.casefold()
        self.assertion_value = str(assertion_value or "").strip()
        # Maps an authenticated gateway subject to concrete, explicitly
        # configured grants. Header roles alone are never authorization.
        self.grants_resolver = grants_resolver

    def authenticate(self, headers: Mapping[str, str]) -> Principal:
        folded = {str(key).casefold(): value for key, value in headers.items()}
        assertion = str(folded.get(self.assertion_header) or "").strip()
        if not self.assertion_value or not secrets.compare_digest(
            assertion, self.assertion_value
        ):
            raise ApiError(
                ErrorCode.UNAUTHENTICATED,
                "A validated gateway assertion is required",
            )
        subject = str(folded.get(self.subject_header) or "").strip()
        if not subject:
            raise ApiError(
                ErrorCode.UNAUTHENTICATED,
                "Upstream gateway did not assert a principal",
            )
        roles = [
            role.strip().casefold()
            for role in str(folded.get(self.roles_header) or "").split(",")
            if role.strip()
        ]
        if self.grants_resolver is None:
            raise ApiError(
                ErrorCode.UNAUTHENTICATED,
                "Upstream gateway authentication requires a configured grants resolver",
            )
        grants = tuple(self.grants_resolver(subject, roles))
        if not grants:
            raise ApiError(
                ErrorCode.UNAUTHENTICATED,
                f"Principal {subject!r} was asserted without any usable role",
            )
        return Principal(subject=subject, grants=grants)


class EntraJwtAuthenticator:
    """Validate Entra access tokens and map asserted app roles to grants."""

    def __init__(
        self,
        *,
        tenant_id: str,
        audience: str,
        grants_resolver: Callable[[str, list[str]], tuple[Grant, ...]],
    ) -> None:
        import jwt

        self.tenant_id = str(tenant_id or "").strip()
        self.audience = str(audience or "").strip()
        if not self.tenant_id or not self.audience:
            raise ValueError("Entra tenant and audience are required")
        # Entra may issue the access token audience as either the app-id URI
        # (e.g. "api://<client-id>") or the bare application (client) ID GUID,
        # depending on tenant/token configuration. Accept both forms so
        # validation doesn't reject legitimately-issued tokens.
        bare_audience = self.audience.removeprefix("api://")
        self.valid_audiences = {self.audience, bare_audience}
        self.issuer = (
            f"https://login.microsoftonline.com/{self.tenant_id}/v2.0"
        )
        self.jwks = jwt.PyJWKClient(
            f"https://login.microsoftonline.com/{self.tenant_id}/discovery/v2.0/keys"
        )
        self.grants_resolver = grants_resolver

    def authenticate(self, headers: Mapping[str, str]) -> Principal:
        import jwt

        token = _bearer_token(headers)
        try:
            signing_key = self.jwks.get_signing_key_from_jwt(token)
            claims = jwt.decode(
                token,
                signing_key.key,
                algorithms=["RS256"],
                audience=list(self.valid_audiences),
                issuer=self.issuer,
                options={"require": ["exp", "iat", "iss", "aud"]},
            )
        except jwt.PyJWTError as exc:
            # No token contents logged -- exc's class name is enough to tell
            # apart expiry, signature/JWKS-key-rollover, and audience/issuer
            # mismatches without risking secret material in logs.
            print(f"entra_token_invalid error={type(exc).__name__} reason={exc}")
            raise ApiError(
                ErrorCode.UNAUTHENTICATED, "Entra access token is invalid"
            ) from exc
        subject = str(
            claims.get("preferred_username")
            or claims.get("upn")
            or claims.get("oid")
            or claims.get("sub")
            or ""
        ).strip()
        roles = [
            str(role).strip().casefold()
            for role in claims.get("roles") or ()
            if str(role).strip()
        ]
        grants = tuple(self.grants_resolver(subject, roles))
        if not subject or not grants:
            # Deliberately no token contents logged. subject/roles are the
            # asserted app-role claim and the resolved subject only -- useful
            # to distinguish "no roles claim" (app role not defined/assigned,
            # or a stale cached token issued before assignment) from
            # "roles present but no matching AIOPS_API_GATEWAY_GRANTS entry"
            # (subject/casefold mismatch, or a role not listed for that
            # subject) without ever exposing token secrets.
            print(
                "entra_grant_denied "
                f"subject={subject!r} roles={roles!r} oid={claims.get('oid')!r} "
                f"has_grants_resolver={self.grants_resolver is not None}"
            )
            raise ApiError(
                ErrorCode.UNAUTHENTICATED,
                "Entra principal has no configured AIOps grants",
            )
        return Principal(subject=subject, grants=grants)


class GatewayOrDirectAuthenticator:
    """Accepts either a validated gateway assertion or a direct Entra token.

    APIM fronts only the governed MCP route, and its inbound policy *deletes*
    the caller's ``Authorization`` header before forwarding a gateway
    assertion. Browser traffic reaches the API directly and can only ever
    present an Entra bearer token. A single global mode cannot serve both:
    ``gateway`` locks every browser call out with "A validated gateway
    assertion is required", while ``entra`` rejects APIM-forwarded MCP calls
    that carry no bearer token at all.

    Routing on the presence of the gateway assertion header keeps both trust
    boundaries intact rather than weakening either. A request bearing the
    header is validated against the configured assertion secret exactly as
    before -- a forged or absent value still fails -- and every other request
    must pass full Entra JWT validation.
    """

    def __init__(
        self,
        *,
        gateway: HeaderPrincipalAuthenticator,
        direct: EntraJwtAuthenticator,
    ) -> None:
        self.gateway = gateway
        self.direct = direct

    def authenticate(self, headers: Mapping[str, str]) -> Principal:
        folded = {str(key).casefold(): value for key, value in headers.items()}
        if str(folded.get(self.gateway.assertion_header) or "").strip():
            return self.gateway.authenticate(headers)
        return self.direct.authenticate(headers)
