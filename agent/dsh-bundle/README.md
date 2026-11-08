# Chilon Teaching Agent — DSH bundle

This is the **current** DSH integration format (DSH 0.2.2+): an agent-preset
declaration carried by a bundle patch, not a `$DSH_HOME/.agent-presets` directory
(that legacy layout is no longer read).

It declares:

```text
preset-chilon-teaching
  └── plugins:
      ├── persona            @deepseek-ai/dsh-persona
      ├── skill-filesystem   @deepseek-ai/dsh-skill-filesystem
      ├── tool-skill         @deepseek-ai/dsh-tool-skill
      ├── mcp-chilon         @deepseek-ai/dsh-mcp-client
      ├── tool-ask-user
      └── tool-todo
```

The MCP child starts `agent/mcp_server.py` and exposes:

```text
mcp__chilon__search_knowledge
mcp__chilon__get_question_detail
mcp__chilon__get_textbook_content
mcp__chilon__get_source_detail
mcp__chilon__calculate_math
```

## Install

The bundle is already installed in the desktop profile. For a new machine:

1. Install the MCP dependency:

```powershell
.venv\Scripts\python.exe -m pip install -r requirements-agent.txt
```

2. Install this directory through DSH's plugin/bundle manager, targeting the
   absolute path:

```text
D:\Chilon\agent\dsh-bundle
```

3. Refresh DSH; a new session can select **Chilon 教学 Agent**.

If the repo moves, update the absolute paths in `cordis.patch.yml` (venv python,
MCP script, skill directory) before reinstalling.

## Verify

```text
Settings → Agent 预设 → Chilon 教学 Agent
```

or via plugin inventory: the row `preset-chilon-teaching` should be active.
