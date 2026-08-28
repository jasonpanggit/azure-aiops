from api.auth import HeaderPrincipalAuthenticator
from api.errors import ApiError
from api.rbac import Grant
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
