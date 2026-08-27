"""
Upgrade Fabric Spark pool configuration via Fabric Admin API.

Phase 08 blocker fix: upgrade Spark pool from Medium (1-3 nodes) to 
Large (1-5 nodes) to provide sufficient compute for notebook execution.
"""

import json
import os
import requests
from typing import Any

def get_access_token() -> str:
    """Get Azure access token for Fabric API calls."""
    tenant_id = os.getenv("AZURE_TENANT_ID")
    client_id = os.getenv("AZURE_CLIENT_ID")
    client_secret = os.getenv("AZURE_CLIENT_SECRET")
    
    if not all([tenant_id, client_id, client_secret]):
        raise ValueError("Missing Azure credentials")
    
    auth_url = f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"
    payload = {
        "grant_type": "client_credentials",
        "client_id": client_id,
        "client_secret": client_secret,
        "scope": "https://analysis.windows.net/powerbi/api/.default",
    }
    
    response = requests.post(auth_url, data=payload)
    response.raise_for_status()
    return response.json()["access_token"]

def upgrade_spark_pool(workspace_id: str, token: str) -> dict[str, Any]:
    """Upgrade workspace Spark pool configuration via admin API."""
    
    # Try admin API endpoint for workspace compute settings
    api_url = f"https://api.powerbi.com/v1.0/admin/workspaces/{workspace_id}/settings"
    
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    
    payload = {
        "netContent": {
            "sparkSettings": {
                "nodeFamily": "MemoryOptimized",
                "nodeSize": "Large",
                "autoScale": {
                    "enabled": True,
                    "minNodes": 1,
                    "maxNodes": 5,
                },
                "dynamicExecutorAllocation": {
                    "enabled": True,
                    "minExecutors": 1,
                    "maxExecutors": 2,
                },
            }
        }
    }
    
    print(f"\n📡 Attempting admin API endpoint...")
    print(f"   URL: {api_url}")
    
    response = requests.patch(api_url, json=payload, headers=headers)
    
    if response.status_code in [200, 201, 202]:
        print("✅ Update accepted via admin API")
        return response.json() if response.text else {"status": "accepted"}
    
    # Fallback: Try capacity compute endpoint
    api_url = f"https://api.powerbi.com/v1.0/myorg/workspaces/{workspace_id}/computeSettings"
    print(f"\n📡 Attempting compute settings endpoint...")
    print(f"   URL: {api_url}")
    
    response = requests.post(api_url, json=payload, headers=headers)
    
    if response.status_code in [200, 201, 202]:
        print("✅ Update accepted via compute settings endpoint")
        return response.json() if response.text else {"status": "accepted"}
    
    print(f"❌ API Error: {response.status_code}")
    print(f"   Response: {response.text}")
    
    # Additional guidance
    print("\n⚠️  Fabric Spark settings may not be available via REST API yet.")
    print("   Manual update required via Fabric UI:")
    print(f"   1. Navigate to workspace: {workspace_id}")
    print("   2. Go to Settings → Workspace Settings")
    print("   3. Find Spark Compute section")
    print("   4. Change Node Size from 'Medium' to 'Large'")
    print("   5. Change Autoscale Max from '3' to '5'")
    
    raise ValueError(f"API endpoint not found: {response.status_code}")

def main():
    workspace_id = os.getenv("FABRIC_WORKSPACE_ID")
    if not workspace_id:
        raise ValueError("Missing FABRIC_WORKSPACE_ID")
    
    print("\n" + "="*70)
    print("FABRIC SPARK POOL UPGRADE")
    print("="*70)
    print(f"Workspace: {workspace_id}")
    print("\nTarget configuration:")
    print("  Node Size: Large")
    print("  Autoscale: 1-5 nodes")
    print("  Dynamic Executors: 1-2")
    
    try:
        token = get_access_token()
        print("\n✅ Authentication successful")
        result = upgrade_spark_pool(workspace_id, token)
        
    except Exception as e:
        print(f"\n⚠️  API approach failed: {e}")
        print("\n" + "="*70)
        print("MANUAL UPDATE REQUIRED")
        print("="*70)
        print("\nFabric Spark settings are managed through the Fabric UI.")
        print("Please update manually:")
        print(f"\n  1. Open Fabric workspace: 1c328da7-2490-48dc-9ba6-de8c1f333756")
        print("  2. Click Settings (gear icon)")
        print("  3. Navigate to 'Workspace Settings' → 'Spark Settings'")
        print("  4. Update Spark Compute configuration:")
        print("     • Node Family: Memory optimized ✓ (already set)")
        print("     • Node Size: Change from 'Medium' to 'Large'")
        print("     • Autoscale max nodes: Change from '3' to '5'")
        print("  5. Click Save")
        print("  6. Wait 2-5 minutes for changes to apply")
        print("  7. Re-run Phase 08 notebooks to test")
        print("\n" + "="*70 + "\n")

if __name__ == "__main__":
    main()
