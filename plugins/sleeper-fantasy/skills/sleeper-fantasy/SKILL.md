---
name: sleeper-fantasy
description: Answer questions about a Sleeper fantasy football league using live Sleeper data. Use for fantasy football questions about rosters, waiver wire / available players, trades and transactions, matchups, injuries, trending pickups, start/sit decisions, trade evaluation, and weekly recaps, whenever the user mentions Sleeper or their fantasy league.
---

# Sleeper fantasy football

Use `scripts/sleeper.py` (in this skill's directory) for all Sleeper data. It handles API calls, caching and player-ID-to-name joins, so never call the Sleeper API directly or read raw JSON. It uses only the Python standard library.

```
python3 "${CLAUDE_SKILL_DIR}/scripts/sleeper.py" <command> [options]
```

## Identifying the league and the user

Preferred: the `SLEEPER_USERNAME` environment variable (or `--username NAME`). The script then finds the user's league for the current season on its own, and knows which team is theirs: it is marked `<- you` and `rosters --team me` works. Use "me" for questions like "my roster", "should I start...", "who should I pick up".

Alternatives: `--league ID` or `SLEEPER_LEAGUE_ID` for a specific league (needed if the user is in several leagues, since the script then lists them and asks you to choose with `--league`). If nothing is set, ask the user for their Sleeper username (not display name); `leagues` can then list their league IDs. Never guess a username or league ID.

## Commands

All commands accept `--json` (structured output) and `--refresh` (refetch the player database; normally cached 24h). Default text output is compact; prefer it.

| Command | Use it for |
|---|---|
| `leagues` | List the leagues for a username and season. Use when the user is in several leagues or you need a league ID. |
| `league` | First call in a conversation. League name, scoring (PPR/half/standard), roster slots, teams with records and points. Also gives the team names and roster IDs other commands use. |
| `rosters [--team NAME]` | A team's players, marked starters / bench / IR / taxi, with position, NFL team, injury label. Use `--team` (substring of team name, owner, or roster id, or `me`) to keep output small. Needed for start/sit, trade evaluation and roster-needs questions. |
| `available [--pos RB] [--limit 25]` | Waiver wire: active unrostered players at positions this league uses, ordered by Sleeper search rank (a popularity proxy, not a quality ranking). `--pos` takes comma-separated positions, e.g. `WR,TE`. |
| `transactions [--week N]` | Completed trades, waiver claims, free-agent adds/drops for a week (default: current). Trades show what each team received and sent, including picks. For a weekly recap, also check the previous week. |
| `matchups [--week N]` | Pairings and points for a week (default: current). |
| `trending [--type add\|drop] [--hours 24] [--limit 25]` | Sleeper-wide trending adds/drops, each marked AVAILABLE or owned by a league team. Best for waiver targets. |
| `player NAME` | Fuzzy lookup: position, team, injury fields, depth chart position, and who owns them in this league. Use it to resolve ambiguous names and check availability. |

## Rules for answering

- **Injuries:** Sleeper's `injury_status` is only a label and can be up to a day stale. For any start/sit question, or any player marked Questionable or worse (Doubtful, Out, IR, PUP, Sus), web search for the latest injury news and practice reports before answering. Say when the latest news changes what Sleeper shows.
- **No news, projections, or rankings in Sleeper.** Use web search for projections, rankings, matchups, snap counts and news. Cite what you found. Never invent stats, projections or injury details; if you can't find something, say so.
- **Search rank is not quality.** `available` order reflects Sleeper's search popularity. Re-rank using web-searched rest-of-season outlook and the league's scoring format and roster slots.
- **Trade evaluation:** pull both rosters (`rosters --team`) so you can assess positional need, plus the scoring format from `league`. Consider depth, bye weeks and injuries (check them by web search).
- **Weekly recaps:** combine `matchups` (this and last week), `transactions`, and `league` standings.
- **Pending trade offers are private.** The API only shows completed trades. Say so if asked about offers on the table.
- **Pre-draft or off-season:** rosters and transactions may be empty or stale. Mention it rather than guessing.

## Errors

- "League not found" means a bad league ID; "user not found" means a bad username. Ask the user to check it.
- Network errors mean Sleeper is unreachable. The skill needs network access to `api.sleeper.app`. It works in Claude Code, but sandboxed environments may block it. Don't retry in a loop. Rate limit is 1000 calls/minute, and each command makes only a handful.
