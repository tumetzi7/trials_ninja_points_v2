# Trials Ninja Points

A points and Elo leaderboard for Trials tracks of every level, from 1 to 10. The current data covers level 7, 8 and 9 tracks. Every recorded pass is scored by how hard the track is and how cleanly it was ridden. Each player's runs are then combined into an effective level, an Elo and a rank from Bronze to SSL.

**Current results:** [player leaderboard](output/player_elo.csv) · [top 25 runs](output/top_runs.csv) · [track ratings](data/track_ratings.csv)

## Running it

Needs Python 3.10+.

```sh
pip install -r requirements.txt
python driver.py
```

This pulls the latest votes from the [track rating sheet](https://docs.google.com/spreadsheets/d/1gBv5KJDzXPCv_MgnghG8_GPwmJ309oVKJwmg9m2z2eg) and rewrites the three output files. The sheet currently lists level 8 and 9 tracks. The sheet has to stay viewable by anyone with the link. Because votes keep coming in, your results can differ from the committed files.

To check the votes themselves (each voter's lean, and the rating each level 8 and 9 track is scored at), run:

```sh
python democratic_ratings.py
```

## How scoring works

1. **Track rating.** A track's rating is the median vote on the sheet. A rating set by hand in `data/track_rating_overrides.csv` overrides the votes. A track with no votes is rated at its flat level: an unvoted level 7 track counts as exactly 7. Turning on `CORRECT_VOTER_LEAN` in `democratic_ratings.py` (off for now) switches scoring to the median after each voter's habitual lean (harsh or soft) is subtracted. The correction never moves a track outside its lowest and highest vote.
2. **Run level.** A run is scored as if its track were rated a bit higher or lower, depending on its faults compared with the track's median pass. A flawless run gets the biggest bonus, a median run lands exactly on the track's rating, and the worst runs score as a track 0.1 levels easier. Time compared with the track median nudges this by at most ±0.01.
3. **Run points.** Each run level is worth points that grow with every level. A median pass is worth 2 median passes one level lower up through level 6, then the steps widen: a median level 7 pass is worth 5 median level 6 passes, level 8 is worth 10 of level 7, level 9 is worth 20 of level 8, and level 10 is worth 30 of level 9.
4. **Player score.** A player's runs are summed best first, osu-style: the best run counts 100%, the next 95%, then 90.25%, and so on. Padding with weak runs adds next to nothing.
5. **Effective level, Elo and rank.** The score is converted back to an effective level, then to an Elo and a rank. A player needs at least 7 runs to be ranked.

| Rank | Starts at level | Elo |
|---|---|---|
| Bronze | 1.0 | 0 |
| Silver | 2.0 | 300 |
| Gold | 4.0 | 600 |
| Platinum | 5.0 | 900 |
| Diamond | 6.0 | 1200 |
| Champ | 7.3 | 1500 |
| Grand Champ | 8.0 | 1800 |
| SSL | 8.75 | 2100 (open-ended, 3350 at level 10) |

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

## Data rules

- Every row in `runs_all.csv` is a pass. Blanks, faults outside 0 to 499 and times outside 0 to 29:59.999 stop the run with an error, since they can only be typos.
- Only full tracks count. Extra-checkpoint versions (names with `+` or `++`, like `Anomaly [+CPs]`, and 50-checkpoint versions like `Deviant [50cps]`) are skipped.
- Sheet votes that aren't a number, or sit more than 1.5 from the track's level (like 85 for 8.5), are skipped with a warning.
