#!/usr/bin/env bash
# Defines the Hermes app roles on the Entra app registration and assigns them
# to the configured HERMES_API_GATEWAY_GRANTS subjects.
#
# Why this is needed: EntraJwtAuthenticator (src/api/auth.py) reads the JWT's
# `roles` claim and intersects it with each subject's grants from
# HERMES_API_GATEWAY_GRANTS (src/api/runtime.py:_gateway_grants). Entra only
# populates a `roles` claim when the app registration defines appRoles AND the
# signed-in user/SP has been assigned one of them. Without this one-time setup,
# every token has an empty roles claim and every principal is rejected with
# "Entra principal has no configured Hermes grants" regardless of what's in
# HERMES_API_GATEWAY_GRANTS.
#
# Requires an identity with Application.ReadWrite.All (or ownership of the app
# registration) -- run this as a tenant/app admin, not the deployment SPN.
#
# Usage:
#   ENTRA_WEB_CLIENT_ID=<app-id> \
#   HERMES_API_GATEWAY_GRANTS='{"admin@contoso.com":[{"role":"admin"}]}' \
#   ./infra/scripts/configure-entra-app-roles.sh

set -euo pipefail

: "${ENTRA_WEB_CLIENT_ID:?Set ENTRA_WEB_CLIENT_ID to the app (client) ID}"
: "${HERMES_API_GATEWAY_GRANTS:?Set HERMES_API_GATEWAY_GRANTS to the same JSON used by the API container app}"

echo "Resolving application object..."
APP_OBJECT_ID="$(az ad app show --id "$ENTRA_WEB_CLIENT_ID" --query id -o tsv)"
SP_OBJECT_ID="$(az ad sp show --id "$ENTRA_WEB_CLIENT_ID" --query id -o tsv)"
echo "  application object id: $APP_OBJECT_ID"
echo "  service principal id:  $SP_OBJECT_ID"

# Fixed, stable role IDs (any valid GUIDs; must stay constant once assigned).
ROLE_ADMIN_ID="8f6c9f1e-1a2b-4c3d-9e4f-6a7b8c9d0e1f"
ROLE_OPERATOR_ID="9a1b2c3d-4e5f-6071-8293-a4b5c6d7e8f9"
ROLE_READER_ID="1c2d3e4f-5a6b-7c8d-9e0f-1a2b3c4d5e6f"

echo "Ensuring appRoles admin/operator/reader are defined..."
cat > /tmp/hermes-app-roles.json <<EOF
{
  "appRoles": [
    {
      "allowedMemberTypes": ["User"],
      "description": "Full administrative access to the Operations Workbench API.",
      "displayName": "Admin",
      "id": "${ROLE_ADMIN_ID}",
      "isEnabled": true,
      "value": "admin"
    },
    {
      "allowedMemberTypes": ["User"],
      "description": "Operate connections and trigger sync/discovery runs.",
      "displayName": "Operator",
      "id": "${ROLE_OPERATOR_ID}",
      "isEnabled": true,
      "value": "operator"
    },
    {
      "allowedMemberTypes": ["User"],
      "description": "Read-only access to Operations Workbench data.",
      "displayName": "Reader",
      "id": "${ROLE_READER_ID}",
      "isEnabled": true,
      "value": "reader"
    }
  ]
}
EOF
az rest --method PATCH \
  --url "https://graph.microsoft.com/v1.0/applications/${APP_OBJECT_ID}" \
  --headers "Content-Type=application/json" \
  --body @/tmp/hermes-app-roles.json

echo "Assigning app roles to configured grant subjects..."
python3 - "$SP_OBJECT_ID" "$ROLE_ADMIN_ID" "$ROLE_OPERATOR_ID" "$ROLE_READER_ID" <<'PY'
import json
import os
import subprocess
import sys

sp_id, admin_role, operator_role, reader_role = sys.argv[1:5]
role_by_name = {"admin": admin_role, "operator": operator_role, "reader": reader_role}

grants = json.loads(os.environ["HERMES_API_GATEWAY_GRANTS"])

# Resolve each subject to its Entra objectId (user UPN or SP appId), then
# assign the highest-configured app role for that subject.
for subject, roles in grants.items():
    role_values = {str(r.get("role", "")).strip().casefold() for r in roles}
    role_id = None
    for candidate in ("admin", "operator", "reader"):
        if candidate in role_values:
            role_id = role_by_name[candidate]
            break
    if role_id is None:
        print(f"skip {subject}: no recognized role in {role_values}")
        continue

    # Resolve subject -> objectId. Try as a user UPN first, then as an app SP.
    principal_id = None
    result = subprocess.run(
        ["az", "ad", "user", "show", "--id", subject, "--query", "id", "-o", "tsv"],
        capture_output=True, text=True,
    )
    if result.returncode == 0 and result.stdout.strip():
        principal_id = result.stdout.strip()
    else:
        result = subprocess.run(
            ["az", "ad", "sp", "show", "--id", subject, "--query", "id", "-o", "tsv"],
            capture_output=True, text=True,
        )
        if result.returncode == 0 and result.stdout.strip():
            principal_id = result.stdout.strip()

    if not principal_id:
        print(f"WARNING: could not resolve principal id for subject {subject!r}; skipping")
        continue

    body = json.dumps({
        "principalId": principal_id,
        "resourceId": sp_id,
        "appRoleId": role_id,
    })
    assign = subprocess.run(
        [
            "az", "rest", "--method", "POST",
            "--url", f"https://graph.microsoft.com/v1.0/servicePrincipals/{sp_id}/appRoleAssignedTo",
            "--headers", "Content-Type=application/json",
            "--body", body,
        ],
        capture_output=True, text=True,
    )
    if assign.returncode == 0:
        print(f"assigned {subject} -> role id {role_id}")
    elif "Permission being assigned already exists" in assign.stderr:
        print(f"{subject} already has role id {role_id}")
    else:
        print(f"FAILED to assign {subject}: {assign.stderr.strip()}")
PY

echo "Done. Users/SPNs must sign out and back in (or re-acquire a token) to pick up the new roles claim."
