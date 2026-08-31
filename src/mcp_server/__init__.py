"""Azure MCP Server for centralized tool execution with per-subscription SPN management.

This module provides a standalone MCP server that:
- Loads subscription connections from OneLake registry
- Resolves SPN credentials from Azure Key Vault
- Routes tool calls to azure-mcp-server library with correct SPN auth
- Exposes HTTP/MCP endpoints for APIM proxy integration
"""

__version__ = "1.0.0"
