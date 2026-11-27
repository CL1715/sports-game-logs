# NBA Game Logs

Look up any NBA player: recent game logs with adjustable stat and range, plus every game against their next opponent. No odds.

Live site: https://cl1715.github.io/nba-game-logs/

## How it stays current
`.github/workflows/update.yml` runs every 2 hours. It downloads the latest box scores from the open
[hoopR NBA dataset](https://github.com/sportsdataverse/hoopR-nba-data) (ESPN data), rebuilds `site/data.json`
with `scripts/build_data.py`, commits it if anything changed, and redeploys GitHub Pages.
Use **Actions → Update stats and deploy → Run workflow** to refresh by hand.

GitHub pauses scheduled workflows after 60 days without commits, so if it stops over the offseason,
re-enable it from the Actions tab.
