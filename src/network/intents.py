"""Personal saved configuration expectations, not probes or change authorization."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from storage.onelake_documents import DocumentConflictError, OneLakeDocumentStore

MAX_TESTS = 20
MAX_RUNS = 10
MAX_BYTES = 512 * 1024
MAX_INT = 9_007_199_254_740_991


class IntentTest(BaseModel):
    """One operator-declared expectation evaluated only from current configuration."""

    model_config = ConfigDict(
        extra="forbid", strict=True, frozen=True, str_strip_whitespace=True
    )
    test_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$")
    name: str = Field(min_length=1, max_length=80)
    source: str = Field(min_length=1, max_length=512)
    destination: str = Field(min_length=1, max_length=512)
    port: int = Field(ge=1, le=65535)
    protocol: Literal["Tcp", "Udp"]
    expected_verdict: Literal["allowed", "denied"]


class SuiteRevision(BaseModel):
    """Every mutation is conditional on the exact reviewed document revision."""

    model_config = ConfigDict(extra="forbid", strict=True)
    expected_revision: int = Field(ge=0, le=MAX_INT - 1)


class SuiteUpdate(SuiteRevision):
    """Replace the complete bounded declaration set, including explicit removal."""

    tests: list[IntentTest] = Field(max_length=MAX_TESTS)

    @model_validator(mode="after")
    def unique_tests(self):
        """Require stable distinct identities even when human names coincide."""
        if len({test.test_id for test in self.tests}) != len(self.tests):
            raise ValueError("Connectivity test identities must be unique")
        return self


class IntentResult(BaseModel):
    """A configuration verdict; unresolved evidence can never satisfy an expectation."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    test: IntentTest
    verdict: Literal["allowed", "denied", "indeterminate"]
    unknown_count: int = Field(ge=0, le=MAX_INT)
    missing_enforcement_count: int = Field(ge=0, le=MAX_INT)
    outcome: Literal["match", "mismatch", "indeterminate"]

    @model_validator(mode="after")
    def valid_outcome(self):
        """Reject persisted or provider contradictions instead of upgrading confidence."""
        expected = (
            "indeterminate"
            if self.verdict == "indeterminate"
            or self.unknown_count
            or self.missing_enforcement_count
            else "match"
            if self.verdict == self.test.expected_verdict
            else "mismatch"
        )
        if self.outcome != expected:
            raise ValueError("Connectivity outcome contradicts configuration evidence")
        return self


class IntentRun(BaseModel):
    """Exact tested declarations and bounded provenance from one explicit batch."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    run_id: str = Field(pattern=r"^[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}$")
    reviewed_revision: int = Field(ge=0, le=MAX_INT - 1)
    started_at: str = Field(max_length=40)
    finished_at: str = Field(max_length=40)
    source_observed_at: str = Field(max_length=64)
    results: list[IntentResult] = Field(min_length=1, max_length=MAX_TESTS)

    @model_validator(mode="after")
    def coherent_run(self):
        """Require aware ordered times and distinct tested identities."""
        start, finish = map(datetime.fromisoformat, (self.started_at, self.finished_at))
        if start.tzinfo is None or finish.tzinfo is None or start > finish:
            raise ValueError("Connectivity run times are invalid")
        if self.source_observed_at:
            observed = datetime.fromisoformat(self.source_observed_at)
            if observed.tzinfo is None or observed > finish:
                raise ValueError("Connectivity observation time is invalid")
        if len({row.test.test_id for row in self.results}) != len(self.results):
            raise ValueError("Connectivity run test identities are not unique")
        return self


class IntentSuite(BaseModel):
    """Exact-principal/effective-scope state with strict bounded immutable receipts."""

    model_config = ConfigDict(extra="forbid", strict=True)
    schema_version: int = Field(ge=1, le=1)
    actor: str
    scope: dict[str, list[str]]
    revision: int = Field(ge=0, le=MAX_INT)
    tests: list[IntentTest] = Field(max_length=MAX_TESTS)
    runs: list[IntentRun] = Field(max_length=MAX_RUNS)

    @model_validator(mode="after")
    def coherent_suite(self):
        """Validate revision order, distinct declarations and receipt chronology."""
        if len({test.test_id for test in self.tests}) != len(self.tests):
            raise ValueError("Connectivity suite test identities are not unique")
        if len({run.run_id for run in self.runs}) != len(self.runs):
            raise ValueError("Connectivity suite receipt identities are not unique")
        revisions = [run.reviewed_revision for run in self.runs]
        if revisions != sorted(set(revisions)) or any(
            r >= self.revision for r in revisions
        ):
            raise ValueError("Connectivity suite receipt revisions are invalid")
        times = [datetime.fromisoformat(run.finished_at) for run in self.runs]
        if times != sorted(times) or (self.revision == 0 and (self.tests or self.runs)):
            raise ValueError("Connectivity suite receipt chronology is invalid")
        return self


class NetworkIntentStore:
    """Persist bounded declarations and receipts via existing local/OneLake CAS."""

    def __init__(self, documents: OneLakeDocumentStore):
        self.documents = documents

    @staticmethod
    def _name(actor: str, scope: dict[str, list[str]]) -> str:
        identity = json.dumps([actor, scope], sort_keys=True, separators=(",", ":"))
        return f"state/network-intents/{hashlib.sha256(identity.encode()).hexdigest()}.json"

    @staticmethod
    def _bytes(payload: dict) -> int:
        return len((json.dumps(payload, indent=2, sort_keys=True) + "\n").encode())

    def _read(self, actor: str, scope: dict[str, list[str]]):
        name = self._name(actor, scope)
        snapshot = self.documents.read_snapshot(name)
        if snapshot.exists and self._bytes(snapshot.payload) > MAX_BYTES:
            raise RuntimeError("Stored connectivity suite exceeds its document limit")
        try:
            state = (
                IntentSuite.model_validate(snapshot.payload)
                if snapshot.exists
                else IntentSuite(
                    schema_version=1,
                    actor=actor,
                    scope=scope,
                    revision=0,
                    tests=[],
                    runs=[],
                )
            )
        except ValidationError as exc:
            raise RuntimeError("Stored connectivity suite schema is invalid") from exc
        if (state.actor, state.scope) != (actor, scope):
            raise RuntimeError("Stored connectivity suite identity is invalid")
        return name, snapshot, state

    def read(self, actor: str, scope: dict[str, list[str]]) -> dict:
        """Recover personal declarations/receipts without contacting current providers."""
        return self._read(actor, scope)[2].model_dump()

    def update(
        self,
        actor: str,
        scope: dict[str, list[str]],
        expected_revision: int,
        *,
        tests: list[IntentTest] | None = None,
        run: IntentRun | None = None,
    ) -> dict:
        """Replace declarations or append one exact reviewed batch, never both."""
        name, snapshot, state = self._read(actor, scope)
        if state.revision != expected_revision:
            raise DocumentConflictError(
                "Connectivity suite changed; reload before continuing"
            )
        if (tests is None) == (run is None):
            raise ValueError("Specify either connectivity declarations or a run")
        if run is not None and (
            run.reviewed_revision != expected_revision
            or [result.test for result in run.results] != state.tests
        ):
            raise ValueError("Connectivity run does not match the reviewed suite")
        updated = IntentSuite(
            schema_version=1,
            actor=actor,
            scope=scope,
            revision=state.revision + 1,
            tests=state.tests if tests is None else tests,
            runs=state.runs if run is None else [*state.runs, run][-MAX_RUNS:],
        ).model_dump()
        if self._bytes(updated) > MAX_BYTES:
            raise ValueError("Connectivity suite exceeds its 512 KiB document limit")
        if snapshot.exists:
            self.documents.replace_if_match(name, updated, expected_etag=snapshot.etag)
        else:
            self.documents.create_only(name, updated)
        return updated
