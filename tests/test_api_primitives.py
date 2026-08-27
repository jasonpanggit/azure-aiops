"""Unit tests for the Operations API primitives: errors, scope, RBAC, evidence."""

from __future__ import annotations

from datetime import datetime

import pytest

from api.auth import HeaderPrincipalAuthenticator
from api.errors import ApiError, ErrorCode, not_implemented, scrub, translate
from api.evidence import (
    CONFIDENCE_HIGH,
    FRESHNESS_FRESH,
    FRESHNESS_STALE,
    FRESHNESS_UNKNOWN,
    Evidence,
    classify_freshness,
    envelope,
)
from api.rbac import Authorizer, Grant, Principal
from api.scope import Scope, scope_attributes
from onboarding.registry import (
    ConnectionNotFoundError,
    DuplicateConnectionError,
)
from onboarding.service import OnboardingError


def _at(value: str) -> datetime:
    return datetime.fromisoformat(value)


class TestErrorTranslation:
    @pytest.mark.parametrize(
        ("exc", "status", "code"),
        [
            (ConnectionNotFoundError("nope"), 404, ErrorCode.NOT_FOUND),
            (DuplicateConnectionError("dupe"), 409, ErrorCode.ALREADY_EXISTS),
            (OnboardingError("bad"), 400, ErrorCode.INVALID_REQUEST),
            (PermissionError("no"), 403, ErrorCode.FORBIDDEN),
            (LookupError("missing"), 404, ErrorCode.NOT_FOUND),
            (NotImplementedError("later"), 501, ErrorCode.NOT_IMPLEMENTED),
            (ValueError("bad input"), 400, ErrorCode.INVALID_REQUEST),
            (TypeError("bad type"), 400, ErrorCode.INVALID_REQUEST),
        ],
    )
    def test_maps_domain_errors_to_http(self, exc, status, code):
        error = translate(exc)
        assert error.status_code == status
        assert error.code == code

    def test_ambiguous_subject_is_a_conflict(self):
        error = translate(ValueError("Subject 'prod' is ambiguous across 2 entities"))
        assert error.code == ErrorCode.AMBIGUOUS
        assert error.status_code == 409

    def test_unknown_exception_does_not_leak_its_message(self):
        error = translate(RuntimeError("connection string Password=hunter2"))
        assert error.status_code == 500
        assert "hunter2" not in error.message
        assert "hunter2" not in str(error.to_dict())

    def test_api_error_rejects_unknown_code(self):
        with pytest.raises(ValueError):
            ApiError("no_such_code", "boom")

    def test_not_implemented_reports_capability_and_roadmap(self):
        error = not_implemented("vulnerability.cve", roadmap="Prompt 17")
        assert error.status_code == 501
        details = error.to_dict()["error"]["details"]
        assert details["capability"] == "vulnerability.cve"
        assert details["roadmap"] == "Prompt 17"


class TestScrub:
    @pytest.mark.parametrize(
        "text",
        [
            "client_secret=abc123def456ghi789",
            "password: SuperSecret12345",
            "Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.payload.signature",
        ],
    )
    def test_removes_secret_shaped_values(self, text):
        cleaned = scrub(text)
        assert "abc123def456ghi789" not in cleaned
        assert "SuperSecret12345" not in cleaned
        assert "eyJhbGciOiJIUzI1NiJ9.payload.signature" not in cleaned

    def test_preserves_benign_text(self):
        assert "connection 'prod'" in scrub("No connection 'prod' exists")

    def test_does_not_redact_prose_mentioning_a_bearer_token(self):
        """Regression: the bearer pattern used to eat 'A bearer token is required'."""
        assert scrub("A bearer token is required") == "A bearer token is required"


class TestScope:
    def test_unrestricted_matches_everything(self):
        assert Scope.unrestricted().is_unrestricted()
        assert Scope.unrestricted().matches({"subscription": "anything"})

    def test_matches_is_case_insensitive(self):
        scope = Scope.from_mapping({"environment": ["Prod"]})
        assert scope.matches({"environment": "PROD"})
        assert not scope.matches({"environment": "dev"})

    def test_intersection_narrows(self):
        a = Scope.from_mapping({"subscription": ["s1", "s2"]})
        b = Scope.from_mapping({"subscription": ["s2", "s3"]})
        assert a.intersect(b).values("subscription") == frozenset({"s2"})

    def test_disjoint_intersection_is_unsatisfiable_not_unrestricted(self):
        """A regression guard: an empty overlap must never widen to 'all'."""
        a = Scope.from_mapping({"subscription": ["s1"]})
        b = Scope.from_mapping({"subscription": ["s9"]})
        result = a.intersect(b)
        assert not result.is_satisfiable()
        assert not result.is_unrestricted()
        assert not result.matches({"subscription": "s1"})
        assert not result.matches({"subscription": "s9"})

    def test_intersection_keeps_dimensions_only_one_side_constrains(self):
        a = Scope.from_mapping({"subscription": ["s1"]})
        b = Scope.from_mapping({"environment": ["prod"]})
        result = a.intersect(b)
        assert result.values("subscription") == frozenset({"s1"})
        assert result.values("environment") == frozenset({"prod"})

    def test_scope_attributes_reads_alternate_key_spellings(self):
        attributes = scope_attributes(
            {"subscriptionId": "S1", "business_service": "Retail"}
        )
        assert attributes["subscription"] == "s1"
        assert attributes["business_service"] == "retail"


class TestRbac:
    def _principal(self, role, **scope):
        return Principal(
            subject="user@example.com",
            grants=(Grant(role=role, scope=Scope.from_mapping(scope or None)),),
        )

    def test_reader_may_read_but_not_operate_or_write(self):
        authorizer = Authorizer()
        reader = self._principal("reader")
        authorizer.require(reader, "read")
        for action in ("operate", "write"):
            with pytest.raises(ApiError) as excinfo:
                authorizer.require(reader, action)
            assert excinfo.value.status_code == 403

    def test_operator_may_operate_but_not_write(self):
        authorizer = Authorizer()
        operator = self._principal("operator")
        authorizer.require(operator, "operate")
        with pytest.raises(ApiError):
            authorizer.require(operator, "write")

    def test_admin_may_do_everything(self):
        authorizer = Authorizer()
        admin = self._principal("admin")
        for action in ("read", "operate", "write"):
            authorizer.require(admin, action)

    def test_effective_scope_narrows_to_granted_subscription(self):
        authorizer = Authorizer()
        principal = self._principal("reader", subscription=["s1"])
        effective = authorizer.effective_scope(principal, "read", Scope.unrestricted())
        assert effective.values("subscription") == frozenset({"s1"})

    def test_cross_subscription_read_is_denied(self):
        """A principal scoped to s1 must not be able to request s2."""
        authorizer = Authorizer()
        principal = self._principal("reader", subscription=["s1"])
        requested = Scope.from_mapping({"subscription": ["s2"]})
        with pytest.raises(ApiError) as excinfo:
            authorizer.effective_scope(principal, "read", requested)
        assert excinfo.value.status_code == 403

    def test_unrestricted_grant_preserves_request(self):
        authorizer = Authorizer()
        principal = self._principal("reader")
        requested = Scope.from_mapping({"subscription": ["s7"]})
        assert authorizer.effective_scope(principal, "read", requested) == requested

    def test_grants_union_across_multiple_grants(self):
        authorizer = Authorizer()
        principal = Principal(
            subject="u",
            grants=(
                Grant("reader", Scope.from_mapping({"subscription": ["s1"]})),
                Grant("reader", Scope.from_mapping({"subscription": ["s2"]})),
            ),
        )
        effective = authorizer.effective_scope(principal, "read", Scope.unrestricted())
        assert effective.values("subscription") == frozenset({"s1", "s2"})

    def test_unrelated_multi_dimension_grants_require_explicit_scope(self):
        authorizer = Authorizer()
        principal = Principal(
            subject="u",
            grants=(
                Grant(
                    "reader",
                    Scope.from_mapping(
                        {"subscription": ["s1"], "business_service": ["retail"]}
                    ),
                ),
                Grant(
                    "reader",
                    Scope.from_mapping(
                        {"subscription": ["s2"], "business_service": ["wealth"]}
                    ),
                ),
            ),
        )

        with pytest.raises(ApiError):
            authorizer.effective_scope(principal, "read", Scope.unrestricted())

        effective = authorizer.effective_scope(
            principal,
            "read",
            Scope.from_mapping({"subscription": ["s1"]}),
        )
        assert effective.values("business_service") == frozenset({"retail"})

    def test_grant_rejects_non_grantable_dimension(self):
        with pytest.raises(ValueError):
            Grant("reader", Scope.from_mapping({"region": ["eastus"]}))

    def test_grant_rejects_unknown_role(self):
        with pytest.raises(ValueError):
            Grant("superuser")

    def test_gateway_headers_without_grant_resolution_are_not_authorization(self):
        authenticator = HeaderPrincipalAuthenticator()
        with pytest.raises(ApiError) as excinfo:
            authenticator.authenticate(
                {
                    "x-ms-client-principal-name": "reader@example.com",
                    "x-ms-client-principal-roles": "admin",
                }
            )
        assert excinfo.value.code == ErrorCode.UNAUTHENTICATED


class TestEvidence:
    def test_freshness_bands(self):
        observed = "2026-01-01T00:00:00Z"
        assert classify_freshness(observed, now=_at("2026-01-01T03:00:00Z")) == (
            FRESHNESS_FRESH
        )
        assert classify_freshness(observed, now=_at("2026-01-05T00:00:00Z")) == (
            FRESHNESS_STALE
        )

    def test_unparseable_timestamp_is_unknown_not_stale(self):
        assert classify_freshness("not-a-date") == FRESHNESS_UNKNOWN

    def test_future_timestamp_is_unknown_not_fresh(self):
        """A future timestamp is a clock fault, not evidence of freshness."""
        assert (
            classify_freshness("2030-01-01T00:00:00Z", now=_at("2026-01-01T00:00:00Z"))
            == FRESHNESS_UNKNOWN
        )

    def test_evidence_carries_every_required_field(self):
        evidence = Evidence(
            source_engine="semantic.SemanticEngine",
            source_table="ontology_entities",
            timestamp="2026-01-01T00:00:00Z",
            subscription_connection="conn-1",
            resource_id="/subscriptions/s1",
            confidence=CONFIDENCE_HIGH,
        )
        payload = evidence.to_dict()
        for field in (
            "source_engine",
            "source_table",
            "timestamp",
            "subscription_connection",
            "resource_id",
            "confidence",
            "freshness",
        ):
            assert field in payload

    def test_evidence_rejects_unknown_confidence(self):
        with pytest.raises(ValueError):
            Evidence(source_engine="x", confidence="very-sure")

    def test_envelope_shape(self):
        body = envelope(
            {"a": 1},
            evidence=Evidence(source_engine="x"),
            scope={"subscription": ["s1"]},
            knowledge_version="v3",
        )
        assert body["data"] == {"a": 1}
        assert len(body["evidence"]) == 1
        assert body["scope"] == {"subscription": ["s1"]}
        assert body["knowledge_version"] == "v3"

    def test_envelope_warns_when_a_result_is_truncated(self):
        body = envelope({"items": [], "truncated": True})
        assert body["warnings"] == [
            "Results are truncated; narrow the scope or use pagination for a complete view."
        ]

    def test_envelope_promotes_hybrid_freshness_metadata(self):
        body = envelope(
            {
                "graph_freshness": "graph-time",
                "live_observed_at": "live-time",
                "source_status": {"azure-resource-graph": "ok"},
            }
        )
        assert body["graph_freshness"] == "graph-time"
        assert body["live_observed_at"] == "live-time"
        assert body["source_status"]["azure-resource-graph"] == "ok"
