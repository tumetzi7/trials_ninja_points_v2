# Trials Ninja Points

A points and Elo leaderboard for Trials tracks of every level, from 1 to 10. The current data covers level 7, 8 and 9 tracks. Every recorded pass is scored by how hard the track is and how cleanly it was ridden. Each player's runs are then combined into an effective level, an Elo and a rank from Iron to Mythic.

**Current results:** [leaderboard page](index.html) · [player leaderboard](output/player_elo.csv) · [top 25 runs](output/top_runs.csv) · [track ratings](data/track_ratings.csv)

## Running it

Needs Python 3.10+.

```sh
pip install -r requirements.txt
python driver.py
```

This pulls the latest votes from the [track rating sheet](https://docs.google.com/spreadsheets/d/1gBv5KJDzXPCv_MgnghG8_GPwmJ309oVKJwmg9m2z2eg) and rewrites the three output files and the leaderboard page, `index.html`. The sheet currently lists level 8 and 9 tracks. The sheet has to stay viewable by anyone with the link. Because votes keep coming in, your results can differ from the committed files.

To check the votes themselves (each voter's lean, and the rating each level 8 and 9 track is scored at), run:

```sh
python democratic_ratings.py
```

## How scoring works

1. **Track rating.** A track's rating is the median vote on the sheet. A rating set by hand in `data/track_rating_overrides.csv` overrides the votes. A track with no votes is rated at its flat level: an unvoted level 7 track counts as exactly 7. Turning on `CORRECT_VOTER_LEAN` in `democratic_ratings.py` (off for now) switches scoring to the median after each voter's habitual lean (harsh or soft) is subtracted. The correction never moves a track outside its lowest and highest vote.
2. **Run worth.** A median pass is worth the track's rating in points. Points grow with every level: a median pass is worth 5 median passes one level lower up through level 7, then 6 at level 8, 8 at level 9 and 10 at level 10. Points are scaled so a median level 8 pass is worth 1,000. Time compared with the track median nudges the run's level by at most ±0.01.
3. **Faults.** Faults move a run's points by a percentage of its worth, soft-capped by track rating, since low faults on the hardest, least consistent tracks are partly luck. The cap is ±10% from level 9 up and widens by 5% per level down (±15% at 8, ±20% at 7, up to ±50% at level 1). A median run keeps exactly its worth, half or double the median faults move it the same amount either way, and nothing passes the cap.
4. **Flawless runs.** A 0f run also scores as if its track were rated higher, by 1.1 levels at level 1 rising evenly to 1.3 at level 10. The bonus fades out by 5% of the track's median faults (on a 100-fault track, 1f keeps 4/5 of it, 2f 3/5, and 5f none), so near-flawless runs don't fall off a cliff.
5. **Player score.** A player's runs are summed best first, osu-style: the best run counts 100%, the next 95%, then 90.25%, and so on. Padding with weak runs adds little.
6. **Effective level, Elo and rank.** The score is converted back to an effective level, then to an Elo and a rank. There's one rank per whole level. A player needs at least 7 runs to be ranked. Ranks are gated by the hardest official level passed: no one ranks above the rank of that level (Mythic needs a level 9 pass), and Elo is held at the top of that rank. The effective level shown is the ungated score.

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

All of these numbers are constants at the top of `points_calculator.py`, each with a comment explaining it. The vote settings (`CORRECT_VOTER_LEAN`, the 1.5 typo gap) are at the top of `democratic_ratings.py`.

## Files

| File | What it is |
|---|---|
| `points_calculator.py` | The scoring model: loading runs, track ratings, fault and time scaling, player Elo |
| `democratic_ratings.py` | Fetches the rating sheet and turns its votes into track ratings |
| `driver.py` | Runs everything and writes the outputs |
| `data/runs_all.csv` | Every recorded pass: `Player, Track, Level, Faults, Time` (time in ms) |
| `data/track_rating_overrides.csv` | Hand-set track ratings that override the sheet: `Track, Level, Rating` |
| `data/track_ratings.csv` | Output: each track's vote count, min/max vote, `MedianRating` (median of the raw votes, used for scoring) and `DemocraticRating` (median after correcting each voter's lean, used instead if `CORRECT_VOTER_LEAN` is turned on). Overrides and the flat-level fallback apply to both. Sorted hardest first by the one in use |
| `output/player_elo.csv` | Output: `Place, Player, Rank, Elo, Level, Runs, Ranked`. Players with fewer than 7 runs are listed with no place |
| `output/top_runs.csv` | Output: the 25 highest-scoring individual runs |
| `build_site.py` | Builds `index.html` from `site/template.html` with the current results baked in. `driver.py` runs it, or run `python build_site.py` on its own |
| `index.html` | Output: the leaderboard page. Players by Elo, every scored run, and a faults-then-time leaderboard for each track. Open it in a browser; it needs no server |

## Data rules

- Every row in `runs_all.csv` is a pass. Blanks, faults outside 0 to 499 and times outside 0 to 29:59.999 stop the run with an error, since they can only be typos.
- Only full tracks count. Extra-checkpoint versions (names with `+` or `++`, like `Anomaly [+CPs]`, and 50-checkpoint versions like `Deviant [50cps]`) are skipped.
- Sheet votes that aren't a number, or sit more than 1.5 from the track's level (like 85 for 8.5), are skipped with a warning.
