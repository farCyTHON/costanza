# MCP setup

`costanza mcp` is a stdio server. The tools are `costanza_read`, `costanza_propose`, and `costanza_now`. The only resource is `costanza://pack`. There is no tool that accepts, dismisses, or edits a ratified entry. `costanza_now` can update NOW. The other sections change only when a person accepts a proposal.

From a checkout, install the extra before a client launches the server:

```
python -m pip install ".[mcp]"
```

`costanza mcp --print-config` does not need the extra. `costanza mcp` with the server actually running does. Without the package, that command exits 1 and prints `next: pip install "costanza[mcp]"`. That hint names the extra. It does not find a release on PyPI, because the project is not published.

The blocks below are the command's output on 2026-10-24. If this page and the command ever disagree, trust the command:

```
costanza mcp --print-config claude-code
costanza mcp --print-config cursor
costanza mcp --print-config vscode
costanza mcp --print-config claude-desktop
```

An unknown client exits 2. `costanza mcp --print-config nope` printed `unknown client 'nope'` and `next: use claude-code, cursor, claude-desktop or vscode`.

## claude-code

```
claude-code: verified 2026-10-15 against https://code.claude.com/docs/en/mcp
An entry with a command and no type is stdio. Add it with:
claude mcp add --transport stdio costanza -- costanza mcp
Or write .mcp.json:
{
  "mcpServers": {
    "costanza": {
      "command": "costanza",
      "args": [
        "mcp"
      ]
    }
  }
}
```

## cursor

```
cursor: verified 2026-10-15 against https://cursor.com/docs/mcp
Write .cursor/mcp.json in the project, or ~/.cursor/mcp.json for the user.
The field table on that page says type is required. The worked examples omit type. This config includes "type": "stdio".
{
  "mcpServers": {
    "costanza": {
      "type": "stdio",
      "command": "costanza",
      "args": [
        "mcp"
      ]
    }
  }
}
```

## vscode

```
vscode: verified 2026-10-15 against https://code.visualstudio.com/docs/agents/reference/mcp-configuration
Write .vscode/mcp.json. The top-level key is servers.
The stdio field table says type is required. The minimal example on that page omits type. This config includes "type": "stdio".
{
  "servers": {
    "costanza": {
      "type": "stdio",
      "command": "costanza",
      "args": [
        "mcp"
      ]
    }
  }
}
```

## claude-desktop

```
claude-desktop: not verified.
No current official page showed the stdio JSON for claude_desktop_config.json, so this command does not print a config.
VS Code's MCP discovery page lists these locations, which is not a schema:
Windows: %APPDATA%\Claude\claude_desktop_config.json
macOS: ~/Library/Application Support/Claude/claude_desktop_config.json
Linux: $XDG_CONFIG_HOME/Claude/claude_desktop_config.json
Check Claude Desktop's own help before writing a local server entry.
```

The date `2026-10-15` is the day those client docs were checked in the program. This page did not re-check the vendor docs. It quotes the command.
