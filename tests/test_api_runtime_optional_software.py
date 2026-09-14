from __future__ import annotations

import logging

from api.runtime import _optional_configuration_data_rows


def test_optional_configuration_data_returns_available_rows() -> None:
    class LogsClient:
        def query_configuration_data(self, workspace_id: str) -> list[dict]:
            assert workspace_id == "workspace-a"
            return [{"SoftwareName": "Example"}]

    assert _optional_configuration_data_rows(LogsClient(), "workspace-a") == [
        {"SoftwareName": "Example"}
    ]


def test_optional_configuration_data_degrades_missing_table(
    caplog,
) -> None:
    class LogsClient:
        def query_configuration_data(self, workspace_id: str) -> list[dict]:
            assert workspace_id == "workspace-without-configuration-data"
            raise RuntimeError(
                "Failed to resolve table or column expression named "
                "'ConfigurationData'"
            )

    with caplog.at_level(logging.WARNING):
        rows = _optional_configuration_data_rows(
            LogsClient(),
            "workspace-without-configuration-data",
        )

    assert rows == []
    assert "live_patch_configuration_data_unavailable" in caplog.text
