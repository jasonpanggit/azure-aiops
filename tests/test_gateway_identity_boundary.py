from collections.abc import Mapping

from api.auth import HeaderPrincipalAuthenticator
from api.errors import ApiError
from api.rbac import Grant, Principal
from api.scope import Scope


def _auth():
    return HeaderPrincipalAuthenticator(
        assertion_value="aiops-apim-v1",
        grants_resolver=lambda subject, roles: (
            (Grant(role="reader", scope=Scope({"subscription": {"sub-1"}})),)
            if subject == "operator@example.com" and "reader" in roles
            else ()
        ),
    )


def test_gateway_requires_overwritten_assertion_and_ignores_scope_headers():
    headers = {
        "x-aiops-gateway-assertion": "aiops-apim-v1",
        "x-ms-client-principal-name": "operator@example.com",
        "x-ms-client-principal-roles": "reader",
        "x-aiops-scope": "sub-attacker",
        "x-aiops-grant": "admin",
        "x-aiops-subscription": "sub-attacker",
        "x-aiops-principal": "attacker",
    }
    principal = _auth().authenticate(headers)
    assert principal.subject == "operator@example.com"
    assert principal.grants[0].scope.values("subscription") == frozenset({"sub-1"})


def test_missing_or_forged_gateway_assertion_is_rejected():
    base = {
        "x-ms-client-principal-name": "operator@example.com",
        "x-ms-client-principal-roles": "reader",
    }
    for value in ("", "forged", "aiops-apim-v2"):
        with __import__("pytest").raises(ApiError):
            _auth().authenticate({**base, "x-aiops-gateway-assertion": value})


def test_direct_entra_caller_is_not_rejected_by_gateway_mode():
    """Enabling APIM must not lock browser traffic out of every non-MCP route.

    APIM's inbound policy deletes the caller's Authorization header and adds a
    gateway assertion, so MCP calls arrive assertion-only. The browser reaches
    the API directly and can only ever send a bearer token. The composite
    authenticator must route on the assertion header rather than forcing one
    scheme on both.
    """
    from api.auth import GatewayOrDirectAuthenticator

    class _StubDirect:
        assertion_header = "x-aiops-gateway-assertion"

        def __init__(self) -> None:
            self.calls: list[Mapping[str, str]] = []

        def authenticate(self, headers):
            self.calls.append(headers)
            return Principal(
                subject="browser@example.com",
                grants=(Grant(role="reader", scope=Scope({"subscription": {"sub-1"}})),),
            )

    direct = _StubDirect()
    auth = GatewayOrDirectAuthenticator(gateway=_auth(), direct=direct)

    # No assertion header -> direct Entra path.
    principal = auth.authenticate({"authorization": "Bearer token"})
    assert principal.subject == "browser@example.com"
    assert len(direct.calls) == 1

    # Assertion header present -> gateway path, still fully validated.
    gateway_principal = auth.authenticate(
        {
            "x-aiops-gateway-assertion": "aiops-apim-v1",
            "x-ms-client-principal-name": "operator@example.com",
            "x-ms-client-principal-roles": "reader",
        }
    )
    assert gateway_principal.subject == "operator@example.com"
    assert len(direct.calls) == 1


def test_forged_gateway_assertion_never_falls_back_to_direct_auth():
    """A bad assertion must fail, not silently retry as a direct Entra call."""
    from api.auth import GatewayOrDirectAuthenticator

    class _AlwaysAllows:
        def authenticate(self, headers):
            return Principal(subject="should-not-be-used", grants=())

    auth = GatewayOrDirectAuthenticator(gateway=_auth(), direct=_AlwaysAllows())
    with __import__("pytest").raises(ApiError):
        auth.authenticate(
            {
                "x-aiops-gateway-assertion": "forged",
                "x-ms-client-principal-name": "operator@example.com",
                "x-ms-client-principal-roles": "reader",
            }
        )
