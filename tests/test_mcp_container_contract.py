from pathlib import Path


def test_mcp_image_installs_api_runtime_dependencies() -> None:
    dockerfile = Path("Dockerfile.mcp").read_text()
    commands = "\n".join(
        line for line in dockerfile.splitlines() if not line.lstrip().startswith("#")
    )

    assert "uv pip compile pyproject.toml --extra api" in commands
    assert "--all-extras" not in commands
    assert 'CMD ["python", "-m", "uvicorn"' in dockerfile
