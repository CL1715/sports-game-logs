# Player Game Logs (NBA + NFL)

Look up any NBA or NFL player: recent game logs with adjustable stat and range, how their next opponent defends their position (ranked vs the league), and every past game against that team. No odds.

Live site: https://cl1715.github.io/nba-game-logs/

## How it stays current
`.github/workflows/update.yml` runs every 2 hours. It downloads the latest NBA box scores from the open
[hoopR NBA dataset](https://github.com/sportsdataverse/hoopR-nba-data) (ESPN data) and NFL weekly stats from [nflverse](https://github.com/nflverse), rebuilds `site/nba.json` and `site/nfl.json`
with `scripts/build_data.py`, commits it if anything changed, and redeploys GitHub Pages.
Use **Actions → Update stats and deploy → Run workflow** to refresh by hand.

GitHub pauses scheduled workflows after 60 days without commits, so if it stops over the offseason,
re-enable it from the Actions tab.
