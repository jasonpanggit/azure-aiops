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
