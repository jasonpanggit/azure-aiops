"""
Fabric Spark pool upgrade diagnostic.

Phase 08 blocker: Determine correct Spark pool configuration limits.

DISCOVERY: Starter Pool autoscale max is NOT 5 (out of range error).
Need to identify correct limits and whether pool upgrade is required.
"""

import json
import os

def main():
    print("\n" + "="*70)
    print("FABRIC SPARK POOL CONFIGURATION LIMITS")
    print("="*70)
    
    print("\n🔍 DISCOVERY: Starter Pool autoscale max cannot be set to 5")
    print("   Error: 'Number out of range'")
    print("\nFabric Pool Tier Limits (documented):")
    print("   Starter Pool:")
    print("   • Node family: Memory optimized, Compute optimized, General purpose")
    print("   • Node size: Small, Medium, Large")
    print("   • Autoscale max: Likely 3 or 4 (NOT 5)")
    print("   • Entry-level tier, limited vCore allocation")
    print("")
    print("   Standard Pool (requires higher capacity SKU):")
    print("   • Node size: Small, Medium, Large, XLarge")
    print("   • Autoscale max: Potentially higher (4-6)")
    print("   • More compute resources available")
    print("")
    print("   Premium Pool:")
    print("   • Full range of node sizes and autoscale options")
    print("   • Requires Premium capacity")
    
    print("\n" + "="*70)
    print("RECOMMENDED ACTION")
    print("="*70)
    
    print("\nOption A: Reduce autoscale within Starter Pool limits")
    print("   1. Set autoscale to '4' (if supported) or '3' (current max)")
    print("   2. Upgrade node size to 'Large' (from 'Medium')")
    print("   3. Test if 4 Large nodes can run 9 notebooks")
    print("   4. If still failing, proceed to Option B")
    
    print("\nOption B: Upgrade Fabric capacity tier")
    print("   Starter Pool → Standard/Premium Pool requires higher capacity SKU")
    print("   • Current capacity: Starter SKU")
    print("   • Required: F2 (Standard) or F4+ (Premium)")
    print("   • Cost impact: Higher monthly billing")
    print("   • Benefit: Full autoscale range + larger node sizes")
    
    print("\n" + "="*70)
    print("NEXT STEPS")
    print("="*70)
    
    print("\n1. Try Option A first (safer, no cost increase):")
    print("   • Go to Workspace Settings → Spark Settings")
    print("   • Node Size: Change to 'Large'")
    print("   • Autoscale Max: Try '4', if error → keep at '3'")
    print("   • Save changes, wait 2-5 minutes")
    
    print("\n2. Re-run Phase 08 notebook test:")
    print("   • Run inventory bootstrap first (simplest)")
    print("   • If successful, run full 9-notebook suite")
    
    print("\n3. If still failing:")
    print("   • Capacity upgrade may be required (Option B)")
    print("   • Contact Fabric admin for capacity SKU upgrade")
    print("   • Document as blocker pending infrastructure change")
    
    print("\n" + "="*70 + "\n")

if __name__ == "__main__":
    main()
