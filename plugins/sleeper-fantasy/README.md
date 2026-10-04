# sleeper-fantasy

A Claude Code plugin that answers questions about your [Sleeper](https://sleeper.com) fantasy football league using live data from Sleeper's public, read-only API.

## Install

```
/plugin marketplace add kevinmfreire/claude-plugins
/plugin install sleeper-fantasy@kevin-plugins
```

## Setup

Set your Sleeper username (the one you log in with, not your display name). The plugin finds your league and knows which team is yours, so "my roster" and "should I start..." just work.

```bash
export SLEEPER_USERNAME=your_username
```

Add that to your shell profile, or to the `env` block of your Claude Code `settings.json`. You can also just tell Claude your username in conversation.

If you are in more than one league, the plugin lists them and you choose with `SLEEPER_LEAGUE_ID` (or by telling Claude which one). `SLEEPER_LEAGUE_ID` also works on its own if you would rather not provide a username; the league ID is the number in your league's Sleeper URL. The script also takes `--username` and `--league` flags.

Requirements: Python 3.8+ (standard library only) and network access to `api.sleeper.app`. This works in Claude Code. Sandboxed environments may block the API.

## What it can do

- League overview, scoring format, standings
- Rosters with starters/bench/IR/taxi and injury labels
- Waiver wire: best unrostered players by position
- Trades, waivers and free-agent moves, including picks traded
- Weekly matchups and scores
- Trending adds/drops, marked by availability in your league
- Player lookups with depth chart and who owns them

Sleeper has no news, projections or rankings, so Claude uses web search for those and for up-to-date injury news.

## Example questions

- Who are the best available RBs?
- What trades happened this week?
- Should I start Player A or Player B this week?
- Who should I target on waivers?
- Give me a weekly recap of the league.
- Is this trade fair: my X for their Y?
- Who owns Player Z, and is he injured?
- Which trending players are still on the wire?

## Limitations

- Pending trade offers are private and cannot be seen. Only completed trades appear.
- Sleeper's injury status can be up to a day stale.
- The player database (~5MB) is cached for 24h at `~/.cache/sleeper-skill/players.json`. Use `--refresh` to force a refetch.

## Using the script directly

```bash
python3 plugins/sleeper-fantasy/skills/sleeper-fantasy/scripts/sleeper.py leagues --username your_username
python3 plugins/sleeper-fantasy/skills/sleeper-fantasy/scripts/sleeper.py rosters --team me
python3 plugins/sleeper-fantasy/skills/sleeper-fantasy/scripts/sleeper.py available --pos RB --limit 10
```

Run with `--help` for all commands.
