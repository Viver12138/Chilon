# DeepSeek Harness preset

This directory is a ready-to-install DSH agent preset.

Composition:

- `dsh-persona` — Chilon Teaching Agent system prompt;
- `dsh-skill-filesystem` — loads `agent/skills/*`;
- `dsh-mcp-client` — starts `agent/mcp_server.py` and exposes:
  - `mcp__chilon__search_knowledge`
  - `mcp__chilon__get_question_detail`
  - `mcp__chilon__get_textbook_content`
  - `mcp__chilon__get_source_detail`
  - `mcp__chilon__calculate_math`
- `tool-skill`, `tool-ask-user`, `tool-todo`.

## Install on this machine

```powershell
pwsh -NoProfile -File agent/install_dsh_preset.ps1
```

Restart or refresh the DSH Web UI, then start a **new session** and choose
`Chilon 教学 Agent` in the preset chip.

The preset uses absolute paths for this checkout (`D:/Chilon`). If the repo moves,
re-run the installer, which rewrites them.

## Prerequisites

```powershell
.venv\Scripts\python.exe -m pip install mcp
```

The MCP child reads `.env` for `CHILON_DATABASE_URL`, `QDRANT_URL`,
`CHILON_QWEN_API_KEY`. The backend/Qdrant must be running before the preset starts.
