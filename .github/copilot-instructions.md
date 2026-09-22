<!-- GSD Configuration — managed by gsd-core installer -->
# Instructions for GSD

- Use the gsd-core skill when the user asks for GSD or uses a `gsd-*` command.
- Treat `/gsd-...` or `gsd-...` as command invocations and load the matching file from `.github/skills/gsd-*`.
- When a command says to spawn a subagent, prefer a matching custom agent from `.github/agents`.
- Do not apply GSD workflows unless the user explicitly asks for them.
- After completing any `gsd-*` command (or any deliverable it triggers: feature, bug fix, tests, docs, etc.), ALWAYS: (1) offer the user the next step by prompting via `ask_user`; repeat this feedback loop until the user explicitly indicates they are done.
<!-- /GSD Configuration -->

## Release coordination

- This repo's release/deployment sequencing is centrally owned by the "Unified deployment session" (project session).
- Whenever you create a pull request in `jasonpanggit/azure-aiops` (via `create_pull_request` or `gh pr create`), immediately notify the "Unified deployment session" with `send_session_message` — do not wait to be asked. Include: PR number, title, branch, base branch, merge state, a one-line scope summary (backend/frontend/infra affected), and whether it's a follow-up to another PR.
- Look up its current session id via `list_sessions_and_chats` (name: "Unified deployment session") rather than hardcoding it, since session ids can change across worktrees/recreation.
- Do this for every PR you open, not just the first one in a session — repeat the notification each time.
- The Unified deployment session will separately notify you once it merges and deploys your PR (PR number, merge time, deployment target, deployed revision/image). Once you receive that, proceed with your own post-deploy validation independently and asynchronously — the Unified deployment session does not wait for your validation before continuing its own queue, so don't expect it to block, and don't block on it either.

## Azure MCP tool calls — known hang, use CLI fallback

- The `azure-*` MCP tools (e.g. `azure-get_azure_bestpractices`) are backed by a Copilot-host-spawned `npm exec @azure/mcp@latest server start` process. As of npm's published `@azure/mcp@3.0.0-beta.45` ("latest"), specific tools (confirmed: `get_azure_bestpractices`) hang indefinitely with no error in this persistent stdio server mode — root cause is npm wrapper log output polluting the same stdout stream carrying MCP JSON-RPC (fixed upstream in changelogged `beta.46`, not yet published to npm — see microsoft/mcp#3732 and `servers/Azure.Mcp.Server/CHANGELOG.md`).
- If an `azure-*` MCP tool call hangs/gets interrupted, don't keep retrying it with different parameter shapes. Immediately fall back to invoking the `azmcp` CLI binary directly via `bash` — one-shot CLI invocations are unaffected (only persistent server mode hangs).
- Find a working `azmcp` binary first: try `which azmcp`, then check common install locations such as `~/.nvm/versions/node/*/bin/azmcp` or entries in `~/.copilot/mcp-config.json`. Prefer any binary NOT resolved via `npm exec @azure/mcp@latest` (i.e. an explicitly pinned/older version), since that's the one observed to work standalone.
- CLI usage mirrors the MCP tool's `command`/`parameters` shape as flags, e.g.:
  ```
  azmcp get_azure_bestpractices get --resource general --action deployment
  azmcp <namespace> <command> --<param1> <value1> --<param2> <value2> ...
  ```
  Run `azmcp <namespace> <command> --help` to discover the exact required flags for any tool before guessing.
- Periodically re-check `npm view @azure/mcp dist-tags` — once a fixed version is published as `latest`, the MCP tool wrapper should work again and this workaround can be dropped.
