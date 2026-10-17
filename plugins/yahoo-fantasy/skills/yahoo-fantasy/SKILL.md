---
name: yahoo-fantasy
description: Help with a Yahoo Fantasy basketball league, especially draft prep and live draft help. Use when the user mentions Yahoo fantasy, a fantasy basketball draft, draft rankings, who to pick next, or building a draft board.
---

# Yahoo fantasy basketball

Yahoo's Fantasy API needs OAuth and cannot submit picks, so draft help runs on a local board plus web search. The user clicks picks in the Yahoo app.

```
python3 "${CLAUDE_SKILL_DIR}/scripts/draft.py" <command> [options]
```

## Learn the league first

Never guess the format. If the user doesn't know it, read it from their signed-in Chrome (load the `claude-in-chrome` skill) on the league's Settings page and Draft page: scoring type (categories or points), the categories, number of teams, roster slots, draft type (snake or auction), draft order and the user's slot.

## Commands

| Command | Use it for |
|---|---|
| `init --teams N --rounds N --slot N [--type snake] [--format 9cat]` | Start a fresh board. Overwrites the old one. |
| `rankings FILE.csv` | Load rankings (columns `rank,name,pos,team,note`). Build the CSV from web-searched rankings that fit the league's format, and cite the source. |
| `pick NAME` | Record a pick as it happens; the slot is worked out from snake order. Fuzzy name match. |
| `undo` | Remove the last pick. |
| `status` | Who is on the clock and how many picks until the user's next. |
| `available [--pos G,F] [--limit 15]` | Best players left by rank. |
| `mine` | The user's roster so far. |
| `board [--last 12]` | Most recent picks. |

## Yahoo API (optional)

`scripts/yahoo.py` reads league data over OAuth: `auth`, `league`, `standings`, `roster`, `free-agents`, `matchup`, `draft-results [--sync]`. It reads `YAHOO_CLIENT_ID`, `YAHOO_CLIENT_SECRET`, `YAHOO_LEAGUE_ID` and `YAHOO_REDIRECT_URI` from the environment, `./.env` or `~/.config/claude-plugins/.env`. Run `auth` once and paste the code back with `auth --code CODE`.

Yahoo may answer 403 "application is not authorized" even with the Fantasy Sports permission ticked on the app. If so, don't retry; fall back to the Chrome or pasted-page route and the local board.

## Rules for answering

- **Rankings come from web search**, not from memory. Cite them, and say when sources disagree. Never invent stats, injuries or ADP.
- **Fit the format.** In category leagues, weigh positional and category balance (turnovers, free throw % and field goal % punt strategies); in points leagues, just raw production.
- **Check injuries** for any player you recommend early, and for rookies and players returning from injury.
- **Live drafts:** after each pick, run `pick`, then `status`. When the user is on the clock, give one recommendation and one fallback, with the reason, and note what the next few picks before their turn are likely to remove.
- **Keep the board honest.** If the user reports a pick you didn't see, record it before advising.
