# yahoo-fantasy

Draft prep and league help for Yahoo Fantasy basketball.

Yahoo's Fantasy API requires OAuth and can't submit picks, so this plugin keeps a local draft board
(`scripts/draft.py`) and uses web search for rankings and news. League settings can be read from a
signed-in Chrome with the `claude-in-chrome` skill.

## Install

```
/plugin marketplace add kevinmfreire/claude-plugins
/plugin install yahoo-fantasy@kevinmfreire
```

## Draft board

```
python3 skills/yahoo-fantasy/scripts/draft.py init --teams 10 --rounds 13 --slot 4 --format 9cat
python3 skills/yahoo-fantasy/scripts/draft.py rankings rankings.csv
python3 skills/yahoo-fantasy/scripts/draft.py pick "Nikola Jokic"
python3 skills/yahoo-fantasy/scripts/draft.py status
python3 skills/yahoo-fantasy/scripts/draft.py available --pos G --limit 10
```

State is stored in `~/.cache/yahoo-fantasy-skill/draft.json`. Rankings CSV columns: `rank,name,pos,team,note`.

## Yahoo API

`scripts/yahoo.py` adds OAuth (`auth`) and read commands: `league`, `standings`, `roster`, `free-agents`,
`matchup`, `draft-results --sync`. Copy `.env.example` to `.env` (or `~/.config/claude-plugins/.env`) and fill in
the credentials from developer.yahoo.com/apps.

Status: sign-in works, but Yahoo has answered 403 "application is not authorized" for the Fantasy endpoints
even with the Fantasy Sports Read permission enabled, so the read commands are untested against live data.
