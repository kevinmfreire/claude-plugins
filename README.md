# claude-plugins

Personal Claude Code plugins and skills, published as a plugin marketplace.

## Install

```
/plugin marketplace add kevinmfreire/claude-plugins
/plugin install <plugin-name>@kevinmfreire
```

## Plugins

| Plugin | Description |
|---|---|
| [sleeper-fantasy](plugins/sleeper-fantasy) | Questions about a Sleeper fantasy football league: rosters, waivers, trades, matchups, start/sit |

## Layout

```
.claude-plugin/marketplace.json   marketplace catalog
plugins/<name>/                   one directory per plugin
  .claude-plugin/plugin.json
  skills/<skill>/SKILL.md
```

Validate after changes with `claude plugin validate .`

## License

MIT
