# Player Game Logs (NBA + NFL)

Look up any NBA or NFL player: recent game logs with adjustable stat and range, how their next opponent defends their position (ranked vs the league), and every past game against that team. No odds.

Live site: https://cl1715.github.io/sports-game-logs/

## How it stays current
`.github/workflows/update.yml` runs every hour. It downloads the latest NBA box scores from the open
[hoopR NBA dataset](https://github.com/sportsdataverse/hoopR-nba-data) (ESPN data) and NFL weekly stats from [nflverse](https://github.com/nflverse), rebuilds `site/nba.json` and `site/nfl.json`
with `scripts/build_data.py`, pulls injury reports, team news and logos from ESPN with `scripts/build_news.py`,
commits the stats if anything changed, and redeploys GitHub Pages.
Use **Actions → Update stats and deploy → Run workflow** to refresh by hand.

GitHub pauses scheduled workflows after 60 days without commits, so if it stops over the offseason,
re-enable it from the Actions tab.

## Features
- Home slate, favorable spots, starred players with a "since your last visit" feed
- Player pages: projections (floor / standard / upside), hit-rate board, situational splits, with/without teammates, matchup vs position, injuries and news
- Team pages (roster projections, what they give up, stat partners) and game previews (tale of the tape, situations incl. dome / cold / wind)
- Advanced tab: percentiles vs position, NBA shot chart and zones vs the opponent's defense, NFL usage (snap / target / air-yards share, WOPR, red zone), target depth and direction, an estimated receiver role, and opponent advanced defense
- Compare two players, pick journal (saved in your browser, auto-graded), accuracy page grading every saved projection
- `scripts/snapshot.py` runs the page in headless Chrome each hour to save pre-game projections to `site/history_*.json`
