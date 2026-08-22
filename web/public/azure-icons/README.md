# Azure architecture icons

Official Microsoft Azure architecture icons (Public Service Icons, V21), downloaded
from <https://learn.microsoft.com/azure/architecture/icons/> and copied here
**unmodified**.

Microsoft's terms permit these icons in architecture diagrams. They are used only
inside the network topology canvas (`src/components/network/TopologyGraph.tsx`) to
depict Azure resources. Accordingly:

- Do not alter the artwork — no recolouring, cropping, rotating, or distorting.
  Node styling frames icons with a border and background tile instead.
- Do not reuse them as general product UI, navigation, or branding.

| File | Azure service |
| --- | --- |
| `virtual-network.svg` | Virtual Networks |
| `subnet.svg` | Subnet |
| `network-interface.svg` | Network Interfaces |
| `firewall.svg` | Firewalls |
| `firewall-policy.svg` | Azure Firewall Policy |
| `firewall-rule.svg` | Firewalls glyph reused for firewall rule nodes |
| `vpn-gateway.svg` | Virtual Network Gateways |
| `expressroute.svg` | ExpressRoute Circuits |
| `bastion.svg` | Bastions |
| `dns.svg` | DNS Private Resolver |
| `private-dns.svg` | DNS Zones |
| `private-endpoint.svg` | Private Link |
| `nat-gateway.svg` | NAT |
| `network-security-group.svg` | Network Security Groups |
| `route-table.svg` | Route Tables |
| `load-balancer.svg` | Load Balancers |
| `application-gateway.svg` | Application Gateways |
| `peering.svg` | Connections |

Workloads reached *through* the network — a VM behind a NIC, a PaaS service
behind a private endpoint — are not network resources, but the topology draws
them so an endpoint is not a dead end:

| File | Azure service |
| --- | --- |
| `virtual-machine.svg` | Virtual Machines |
| `vm-scale-set.svg` | VM Scale Sets |
| `cosmos-db.svg` | Azure Cosmos DB |
| `postgresql.svg` | Azure Database for PostgreSQL |
| `sql-server.svg` | SQL Server |
| `key-vault.svg` | Key Vaults |
| `storage-account.svg` | Storage Accounts |
| `container-registry.svg` | Container Registries |
| `container-app.svg` | Container Apps Environments |
| `app-service.svg` | App Services |

To add a service kind, place the unmodified official SVG here and map it in
`SERVICE_ICONS` in `src/lib/network-graph.ts`. To add a workload, map its ARM
type in `_WORKLOAD_ENTITY_TYPE_BY_PROVIDER` (`src/network/topology.py`) and the
resulting entity type in `RESOURCE_ICONS`.
