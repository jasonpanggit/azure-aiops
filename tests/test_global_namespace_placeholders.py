"""Guard against placeholder names that collide with global Azure namespaces.

Azure Key Vault and Storage Account names resolve in a single global DNS
namespace. A name such as ``kv-test`` is not an inert placeholder -- it is a
real address, and obvious names are long since registered to unrelated
tenants.

When a client resolves one of those hostnames, Key Vault answers with a
``WWW-Authenticate`` challenge naming the *owning* tenant. Because no local
account exists in that tenant, token acquisition cannot complete silently and
falls back to an interactive browser sign-in prompt.

This test keeps such names out of the repository. It performs no network
access; every check is a static scan of tracked source, test, and doc files.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent

SCAN_DIRS = ("src", "tests", "docs", "scripts")
SCAN_SUFFIXES = {".py", ".md", ".yaml", ".yml", ".json", ".sh", ".bicep", ".tf", ".ts", ".tsx"}

SKIP_DIR_NAMES = {"__pycache__", "node_modules", ".venv", "venv", ".git", "fixtures"}

# A placeholder is safe when it is clearly not a resolvable name: an
# angle-bracket token, a template/f-string interpolation, prose elision, or a
# name carrying a reserved-for-documentation marker. RFC 2606 reserves
# "example" for exactly this purpose.
SAFE_NAME_PATTERN = re.compile(
    r"""
      ^<.+>$          # <your-vault-name>
    | example         # RFC 2606 documentation name
    | \$\{            # ${SHELL_VAR}
    | ^\{.+\}$        # {python_format} / f-string field
    | \{\{            # {{ template }}
    | \.\.\.          # prose elision, e.g. keyvault://...
    """,
    re.IGNORECASE | re.VERBOSE,
)

# Azure-reserved labels that appear in the same hostname position as an account
# name but are not accounts -- e.g. the Private DNS zone
# ``privatelink.blob.core.windows.net``.
RESERVED_LABELS = frozenset({"privatelink"})

VAULT_REFERENCE_PATTERNS = (
    # keyvault://<name>/secrets/...
    re.compile(r"keyvault://([^/\s\"']+)"),
    # az keyvault ... --vault-name <name>
    re.compile(r"--vault-name[=\s]+([^\s\\\"']+)"),
    # <name>.vault.azure.net
    re.compile(r"\b([A-Za-z0-9][A-Za-z0-9-]{1,22}[A-Za-z0-9])\.vault\.azure\.net"),
)

STORAGE_REFERENCE_PATTERNS = (
    re.compile(r"\b([a-z0-9]{3,24})\.blob\.core\.windows\.net"),
    re.compile(r"\b([a-z0-9]{3,24})\.dfs\.core\.windows\.net"),
)


def _scan_files() -> list[Path]:
    files: list[Path] = []
    for directory in SCAN_DIRS:
        root = REPO_ROOT / directory
        if not root.is_dir():
            continue
        for path in root.rglob("*"):
            if path.suffix not in SCAN_SUFFIXES:
                continue
            if SKIP_DIR_NAMES.intersection(path.parts):
                continue
            if path.name == Path(__file__).name:
                continue
            files.append(path)
    return files


def _collect_violations(patterns: tuple[re.Pattern[str], ...]) -> list[str]:
    violations: list[str] = []
    for path in _scan_files():
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            for pattern in patterns:
                for match in pattern.finditer(line):
                    name = match.group(1)
                    if name.lower() in RESERVED_LABELS:
                        continue
                    if SAFE_NAME_PATTERN.search(name):
                        continue
                    relative = path.relative_to(REPO_ROOT)
                    violations.append(f"{relative}:{lineno}: {name!r}")
    return sorted(set(violations))


def test_key_vault_names_are_non_resolvable_placeholders() -> None:
    """Key Vault references must not name a potentially real, foreign vault."""
    violations = _collect_violations(VAULT_REFERENCE_PATTERNS)
    assert not violations, (
        "Key Vault names occupy a single global namespace; a generic name is "
        "almost certainly registered to another tenant, and resolving it "
        "triggers an interactive sign-in prompt against that tenant.\n"
        "Use '<your-vault-name>' in docs or a name containing 'example' in "
        "tests.\n\n" + "\n".join(violations)
    )


def test_storage_account_names_are_non_resolvable_placeholders() -> None:
    """Storage account references must not name a potentially real account."""
    violations = _collect_violations(STORAGE_REFERENCE_PATTERNS)
    assert not violations, (
        "Storage account names occupy a single global namespace. Use "
        "'<your-storage-account>' in docs or a name containing 'example' in "
        "tests.\n\n" + "\n".join(violations)
    )
