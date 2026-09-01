# Telemachos Claude Code Integration

This directory contains the Claude Code skill bundle for Telemachos.

## User Flow

1. Open Telemachos Settings > Integrations.
2. Add a Claude Agent.
3. Copy the full setup commands shown after the generated token.
4. Toggle the tools Claude is allowed to use.
5. Configure the terminal Claude Code session:

```bash
export TELEMACHOS_URL=http://your-telemachos-host:7000
export TELEMACHOS_API_TOKEN=ody_generated_token
mkdir -p ~/.claude
curl -fsSL -H "Authorization: Bearer $TELEMACHOS_API_TOKEN" "$TELEMACHOS_URL/api/claude/plugin.zip" -o /tmp/telemachos-claude-skill.zip
python3 -m zipfile -e /tmp/telemachos-claude-skill.zip ~/.claude/
```

Claude Code auto-loads anything under `~/.claude/skills/`, so the `telemachos` skill is
available in any session that has `TELEMACHOS_URL` and `TELEMACHOS_API_TOKEN` in its
environment.

## What's in the bundle

- `skills/telemachos/SKILL.md` — the skill definition Claude Code reads.
- `skills/telemachos/scripts/telemachos_api.py` — small helper that calls the scoped
  `/api/codex/*` endpoints (these are the canonical scope-gated agent API; the
  `codex` path is historic and shared by all agent integrations).

## Scope enforcement

The token is scope-gated. Every tool surface is checked server-side in Telemachos,
so even if Claude tries to call a forbidden endpoint, it gets `403` until the
user enables the matching toggle in Settings > Integrations > Claude Agent.
