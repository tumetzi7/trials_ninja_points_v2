# Trials Ninja Points

A points and Elo leaderboard for Trials tracks of every level, from 1 to 10. The current data covers levels 1 to 9: about 69,000 runs by 2,300 players. Every recorded pass is scored by how hard the track is and how cleanly it was ridden. Each player's runs are then combined into an effective level, an Elo and a rank from Iron to Mythic, plus a total of every run's points with its own gem rank.

**Current results:** [leaderboard page](index.html)

## Where the data comes from

Track ratings come from the community [track rating sheet](https://docs.google.com/spreadsheets/d/1gBv5KJDzXPCv_MgnghG8_GPwmJ309oVKJwmg9m2z2eg), where riders vote on how hard each track is. It currently lists level 8 and 9 tracks; some tracks also have a rating set by hand.

Runs come from two files. `data/ninja_runs.csv` is the game export: every player's best run on every ninja track, all levels. `data/runs_curated.csv` is the hand-collected level 7 to 9 list the rating sheet is built on. Every run in either file counts, once: where a player has a run on the same track in both, their better one is used (fewest faults, then fastest). A track the curated file lists takes its level from that file (the export puts some, like Sinister, a level off), but only when the two levels are at most one apart; further apart, it's a different track with the same name (the export's level 2 Halcyon is not the curated level 7 one). Clan tags (`[QK] `) are dropped so names match the export.

## How scoring works

1. **Track rating.** A track's rating is the median vote on the sheet. A rating set by hand in `data/track_rating_overrides.csv` overrides the votes. A track with no votes is rated at its flat level: an unvoted level 7 track counts as exactly 7.
2. **Run worth.** A median pass is worth the track's rating in points. A median pass is worth 25 points at level 1, 50 at 2, 100 at 3, 200 at 4, 500 at 5, 1,000 at 6, 2,500 at 7, 5,000 at 8, 10,000 at 9 and 20,000 at 10, rising smoothly in between, so low-level runs are worth real points. Level 9 tracks score at their full rating, so each 0.1 inside level 9 adds about 7%. Time compared with the track median nudges the run's level by at most ±0.01.
3. **Faults.** Faults move a run's points by a percentage of its worth, soft-capped by track rating, since low faults on the hardest, least consistent tracks are partly luck. The cap is ±5% from level 9 up, so there the track's rating decides and a harder track's pass beats an easier one's unless it's a 0f or low-fault run. It widens by 5% per level down (±10% at 8, ±15% at 7, up to ±45% at level 1). A median run keeps exactly its worth, half or double the median faults move it the same amount either way, and nothing passes the cap.
4. **Flawless runs.** A 0f run also scores as if its track were rated higher: by 2.05 levels up to level 5, 1.85 at level 6, 1.5 at level 7 and 1.3 from level 8 up, in straight lines between (a 7.5 track gets 1.4). The bonus shrinks with level because points already climb steeply at the top, and stays flat below level 5 because low-level 0fs are common. A 0f is special, so 1f drops to 63% of the bonus, which makes a 0f worth about 1.38 times a 1f from level 8 up, 1.45 times at level 7 and 1.94 times at level 5. From 1f that fades evenly to nothing by 20% of the track's median faults, never sooner than 2f, so 0f to 1f is the only steep drop (on a 100-fault track, 1f keeps 63%, 5f 50%, 10f 33% and 20f none).
5. **Two leaderboards.** The players board has two orders, for two kinds of player:
   - **Elo (skill).** A player's runs are summed best first, and each counts 87.5% of the one above it: the best run counts 100%, the 10th 30%, the 20th 8% and the 50th 0.1%. A player's best 20 or so runs decide their Elo, so a few hard passes outweigh any number of easier ones, and padding with more runs adds nothing.
   - **Total points (the grind).** Every run's points added up, with no decay and no minimum runs, so every pass counts. It has its own ranks, gems (below).
6. **Effective level, Elo and rank.** The Elo score is divided by the decayed weight of 12 runs (`REFERENCE_RUNS`) and converted back to an effective level, then to an Elo and a rank. There's one rank per whole level. `REFERENCE_RUNS` sets where effective levels land, not the order: 12 puts 7 riders in Mythic. A player needs at least 7 runs to be ranked. Ranks are gated by the hardest official level passed: no one ranks above the rank of that level (Mythic needs a level 9 pass), and Elo is held at the top of that rank. The effective level shown is the ungated score.

| Rank | Effective level | Elo at start |
|---|---|---|
| Iron | 1–2 | 0 |
| Bronze | 2–3 | 300 |
| Silver | 3–4 | 600 |
| Gold | 4–5 | 900 |
| Platinum | 5–6 | 1200 |
| Diamond | 6–7 | 1500 |
| Champ | 7–8 | 1800 |
| Grand Champ | 8–9 | 2100 |
| Mythic | 9+ | 2500 |

Each rank splits into three tiers by effective level, I to III with III the highest: Champ I starts at 7.0, Champ II at 7.33 and Champ III at 7.67.

All of these numbers are constants at the top of `points_calculator.py`, each with a comment explaining it. `MAX_COUNTED_RUNS` (0, meaning all) can limit a player's score to their best runs.

### Total points ranks (gems)

The total points board has its own ladder, a twin of the Elo one: nine gems split I to III, and Obsidian on its own at the top (Quartz matches Iron, Pearl matches Mythic). Each division starts at a fixed points total, so a gem only changes when the player's own total does. They're `POINTS_RANKS` in `points_calculator.py`.

| Gem | I | II | III |
|---|---|---|---|
| Quartz | 0 | 100 | 200 |
| Amber | 400 | 800 | 1,200 |
| Topaz | 1,600 | 2,400 | 3,200 |
| Aquamarine | 4,000 | 6,000 | 8,000 |
| Amethyst | 10,000 | 15,000 | 20,000 |
| Sapphire | 25,000 | 35,000 | 45,000 |
| Emerald | 60,000 | 80,000 | 110,000 |
| Ruby | 150,000 | 225,000 | 350,000 |
| Pearl | 600,000 | 800,000 | 1,000,000 |
| Obsidian | 1,250,000 | | |

For scale: a median pass on every track in the game is about 1.18M points, and every level 7, 8 and 9 track at median about 760k. Obsidian is roughly a player with every level 8 and 9 passed, a level 8 0f and five level 7 0fs, plus a buffer. Nobody holds it yet.

### The page

- **Players** has two boards, switched at the top right. **Elo**: rank, Elo and effective level, with a chart of how many players with 7 or more runs hold each rank division. **Total points**: gem rank, points and runs; level chips count only those levels' runs, and the Points and Runs headers sort.
- The **i** button next to Rank, on either board or a player page, shows every rank's divisions, what each starts at and how many players hold it (for Elo ranks, also the level you must pass).
- **Player pages** show both ranks, a chart of where their Elo comes from by level (levels over 1%), split into passes, low-fault runs and 0f runs (hover a section for its exact share), their runs, and **Level progress**: how many tracks they've passed at each level and which are missing.
- **Top runs** lists every run by points (**0f only** filters it). **Tracks** lists every track, hardest first, with its record holder; each track has a faults-then-time leaderboard.
- The **search box** filters the page you're on and lists matching players and tracks to jump to.
- **Calculator** (or "Score a run on this track" on any track page): pick a track, enter faults and a time (blank, or the Median buttons, for the track median), and it shows the points, step by step, and where the run would place on that track and overall. Add a player (or use "Score a run" on their page) and it also shows what the run would do to them: Elo gained, new place, rank and total points. It scores the run as if it were added and rescores everyone (nothing is saved), so the track's medians shift as they would for a real run. A run that doesn't beat the player's own run on that track changes nothing.
- **Pass grid** (Tracks, then Pass grid): pick a level at the top. Every track of that level, easiest at the top, against every player with a pass there, most passes on the left, like the rating sheet. Under each name is how many of the level's tracks they've passed (like 39/43). Each cell shows the player's faults there, shaded for a 0f or a run under the track's median faults; hover it for the time and placing. Lower levels have hundreds of players, so only the top 50 show. Search finds any player, or narrows the tracks if no player matches. Links like `#grid:7` open a level.
- **Compare** (or "Compare" on a player page): two players side by side. Their headline numbers with the better one highlighted, how many shared tracks each is ahead on (faults, then time), and a table of the tracks both have passed, or the tracks only one of them has. Picking one player suggests the players either side of them on the Elo board. Links look like `#vs:p-pennyjx:p-livinglegend3d`.

Everything else (the median prior, the time shift, track ratings, ranks and the Elo curve) is only in the Python. The sheet settings (its id, the 1.5 typo gap) are at the top of `rating_sheet.py`.

## Files

The CSV files below stay local and are not in the repository (`.gitignore` skips every `.csv`). The published page carries the runs, players and track ratings it needs baked in, gzipped and base64-encoded, so there's no readable table in it. Anyone determined can still decode it, so `build_site.py` puts in only what the page shows: player names, tracks and each run's faults and time. User and track ids never go in.

| File | What it is |
|---|---|
| `points_calculator.py` | The scoring model: loading runs, track ratings, fault and time scaling, player Elo |
| `rating_sheet.py` | Fetches the rating sheet and reads its votes |
| `driver.py` | Puts it all together: loads the runs and votes, writes the outputs and builds the page |
| `data/ninja_runs.csv` | Game export, all levels: `username, user id, track name, track id, ninja level, faults, time` (time in ms) |
| `data/runs_curated.csv` | Hand-collected level 7 to 9 passes: `Player, Track, Level, Faults, Time` (time in ms). Sets the level of each track it lists |
| `data/track_levels.csv` | Hand-set ninja levels for export tracks the game files under the wrong level: `Track, Level` (Incendiary is a 7, not a 4) |
| `data/excluded_runs.csv` | Junk runs to drop, such as bug passes with impossible times: `Player, Track, Level, Faults, Time, Reason` (time in ms). A run is dropped only if every field matches, so a later real run on the same track still counts |
| `data/track_rating_overrides.csv` | Hand-set track ratings that override the sheet: `Track, Level, Rating` |
| `data/track_ratings.csv` | Output: each track's vote count, min/max vote and `Rating`, the rating it's scored at (override, else median vote, else flat level). Sorted hardest first |
| `output/player_elo.csv` | Output: `Place, Player, Rank, Elo, Level, Runs, Ranked, TotalPoints, PointsRank`. Players with fewer than 7 runs are listed with no place |
| `output/top_runs.csv` | Output: the 25 highest-scoring individual runs |
| `build_site.py` | Builds `index.html` from `site/template.html` with the runs, track ratings and scoring constants baked in. |
| `site/template.html` | The page. Its `scoring` script is a JavaScript copy of the scoring in `points_calculator.py` (the page scores every run itself from the raw runs); a change to how scoring works has to be made in both |
| `index.html` | Output: the leaderboard page. Players by Elo and by total points with their ranks, every scored run, a faults-then-time leaderboard for each track, the points calculator and player comparisons. |

## Data rules

- Every row in either runs file is a pass. Blanks, faults outside 0 to 499 and times outside 0 to 29:59.999 stop the run with an error, since they can only be typos.
- Runs listed in `data/excluded_runs.csv` are dropped before each player's best run per track is picked, so a real run in the other file can take their place.
- The same track uploaded twice under different names is merged under one name by `TRACK_RENAMES` in `points_calculator.py` (`shyu park [FIX*]` is SHYU PARK), keeping each player's better run.
- A player with no username in the export is shown as `Player` plus the start of their user id. Two different tracks with the same name and level get their track id appended (`Kid's Toy #146379`).
- Only full tracks count. Extra-checkpoint versions (names with `+` or `++`, like `Anomaly [+CPs]`, and 50-checkpoint versions like `Deviant [50cps]`) are skipped.
- Sheet votes that aren't a number, or sit more than 1.5 from the track's level (like 85 for 8.5), are skipped with a warning.
