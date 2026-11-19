import math
import os

import polars as pl

from democratic_ratings import track_votes


# CONSTANTS
# --------------------------------------------------------------------------------------------------------------------------------------------------------------------
RUN_DECAY = 0.95                   # Osu-style weighting: best run counts 100%, next 95%, then 90.25%... so padding with weak runs adds next to nothing
MIN_RUNS = 7                       # Players need this many runs to be ranked. Also how many median level X passes make a level X rider

# Ranks: (rank, effective level it starts at). One rank per whole level; the last row is open-ended and untiered
RANKS = [
    ("Iron",         1.0),
    ("Bronze",       2.0),
    ("Silver",       3.0),
    ("Gold",         4.0),
    ("Platinum",     5.0),
    ("Diamond",      6.0),
    ("Champ",        7.0),
    ("Grand Champ",  8.0),
    ("Mythic",       9.0),
    ("Divine",       9 + 5 / 6),   # 3000 Elo
]

RANK_TIERS = ["I", "II", "III"]    # Each rank but the last splits into equal tiers by effective level, III the highest (Champ I starts at 7.0, II at 7.33, III at 7.67)

# Elo: (effective level, Elo), interpolated between rows. Each rank is a 300 Elo band up to Champ; bands widen above that so the top spreads out
# (Grand Champ 400, then wider), and the last line carries on above level 10 at 600 Elo per level
ELO_CURVE = [
    (1.0,  0),                     # Iron
    (2.0,  300),                   # Bronze
    (3.0,  600),                   # Silver
    (4.0,  900),                   # Gold
    (5.0,  1200),                  # Platinum
    (6.0,  1500),                  # Diamond
    (7.0,  1800),                  # Champ
    (8.0,  2100),                  # Grand Champ
    (9.0,  2500),                  # Mythic
    (10.0, 3100),                  # Level 10
]

MAX_FAULTS = 499                   # Game cap: 500f = fault out
MAX_TIME = (30 * 60 * 1000) - 1    # Game cap: 29:59.999 in ms

# Level worth: (level, how many median passes of that level one median pass a level higher is worth). Points are scaled by POINTS_AT_LEVEL_8
# Worth climbs at a steady rate between whole levels; the first row's step carries on below it and the last row's above it
LEVEL_STEPS = [
    (1,    5),                     # Steps of 5 below level 7 keep padding with easy passes worth about as little as at the top
    (2,    5),
    (3,    5),
    (4,    5),
    (5,    5),
    (6,    5),
    (7,    6),                     # A median level 8 pass is worth 6 median level 7 passes
    (8,    8),                     # A median level 9 pass is worth 8 median level 8 passes
    (9,    10),                    # A median level 10 pass is worth 10 median level 9 passes
]


# FAULT & TIME SCALING
# --------------------------------------------------------------------------------------------------------------------------------------------------------------------
'''
Faults move a run's points by a percentage, soft-capped by track rating: low-fault runs are partly luck, more so on harder, less consistent tracks.
  points = track worth x (1 + cap x tanh(FAULT_STEEPNESS x ln(median faults / faults)))
A median run gets exactly the track's worth; half or double the median move it the same amount either way; nothing passes +-cap.
Flawless runs are the exception: a 0f run is also scored as if its track were rated ZERO_FAULT_BONUS levels higher. That bonus
fades out by ZERO_FAULT_TAPER of the track's median faults (on a 100-fault track: 1f keeps 4/5, 2f 3/5 ... 5f none) so near-0f runs don't fall off a cliff.
'''

FAULT_CAP = [                      # (track rating, most faults can add or remove, as a share of the run's points); +5% per level down, flat at 10% from level 9 up
    (1,    0.50),
    (2,    0.45),
    (3,    0.40),
    (4,    0.35),
    (5,    0.30),
    (6,    0.25),
    (7,    0.20),                  # Lower levels are more consistent, so fault differences say more about skill and earn more
    (8,    0.15),
    (9,    0.10),                  # The hardest tracks: low faults are mostly luck
]
FAULT_STEEPNESS = 1.3              # How fast the cap is approached: higher spreads runs near the median further apart
ZERO_FAULT_BONUS = [               # Levels added to a 0f run, by track rating: rises evenly from 1.1 at level 1 to 1.3 at level 10 (+0.0022 per 0.1)
    (1,    1.10),
    (10,   1.30),
]
ZERO_FAULT_TAPER = 0.05            # The 0f bonus fades to nothing by this share of the track's median faults (5f on a 100-fault track, 2.5f on a 50)
FAULT_MEDIAN_PRIOR_RUNS = 5        # Track fault medians are pulled toward the level median as if it were 5 extra runs

# Time shift, in levels: TIME_SHIFT_MAX times how much faster than the track median the run was (half the median time = +0.005); slower runs lose the same way
TIME_SHIFT_MAX = 0.01              # Most a run can gain or lose; kept weak since faults and time move together

# Track ratings: Median vote from the opinion sheet (democratic_ratings.py); unvoted tracks use the flat level
OVERRIDES_PATH = "data/track_rating_overrides.csv"   # Hand-set ratings; overrides votes for any track listed with a rating


# Full runs database - one row per run
RUNS_SCHEMA = {
    "Player": pl.Utf8,
    "Track": pl.Utf8,
    "Level": pl.Int64,
    "Faults": pl.Int64,
    "Time": pl.Float64,
}

# Extra-checkpoint versions are left out; only full tracks count. They are named with + or ++ (Anomaly [+CPs], Hattusa ++CP, Whitespire (+CPs),
# Steel Wave +) or 50 checkpoints (Deviant [50cps], Hattusa 50 Cps Fix). No full track has a + in its name
EXTRA_CP_PATTERN = r"(?i)\+|50\s*cps"


def load_runs(path="data/runs_all.csv"):
    # Every row is a pass, so a blank or a value past a game cap can only be a data-entry error: stop rather than score it
    runs = pl.read_csv(path, schema=RUNS_SCHEMA)
    bad = runs.filter(
        pl.any_horizontal(pl.all().is_null())
        | ~pl.col("Faults").is_between(0, MAX_FAULTS)
        | ~((pl.col("Time") > 0) & (pl.col("Time") <= MAX_TIME))
    )
    if bad.height:
        raise ValueError(
            f"{bad.height} rows in {path} break the rules (no blanks, 0 to {MAX_FAULTS} faults, "
            f"time above 0 and under 30:00):\n{bad}"
        )
    return runs.filter(~pl.col("Track").str.contains(EXTRA_CP_PATTERN))


# Level Worth
# --------------------------------------------------------------------------------------------------------------------------------------------------------------------

def interpolate(x, points):
    # Straight lines through (x, y) rows sorted by rising x; the first and last lines carry on past the ends
    i = 1
    while i < len(points) - 1 and x > points[i][0]:
        i += 1
    (x0, y0), (x1, y1) = points[i - 1], points[i]
    return y0 + (y1 - y0) * (x - x0) / (x1 - x0)


assert all(
    row[0] == LEVEL_STEPS[0][0] + i and row[1] > 1 for i, row in enumerate(LEVEL_STEPS)
), "LEVEL_STEPS needs one row per level, none skipped, each step above 1"

# (level, ln worth) rows: each level's ln worth is the one below plus ln of its step
LEVEL_LOG_WORTH = [(LEVEL_STEPS[0][0], 0.0)]
for level, step in LEVEL_STEPS:
    LEVEL_LOG_WORTH.append((level + 1, LEVEL_LOG_WORTH[-1][1] + math.log(step)))

POINTS_AT_LEVEL_8 = 1000           # Display scale only: a median level 8 pass is worth this many points. Rankings don't depend on it
POINTS_SCALE = POINTS_AT_LEVEL_8 / math.exp(interpolate(8, LEVEL_LOG_WORTH))


def level_scaler(level):
    # Points a median pass on a track of this rating is worth
    return POINTS_SCALE * math.exp(interpolate(level, LEVEL_LOG_WORTH))


def level_from_worth(worth):
    # Inverse of level_scaler
    return interpolate(math.log(worth / POINTS_SCALE), [(log_worth, level) for level, log_worth in LEVEL_LOG_WORTH])


# Track Ratings
# --------------------------------------------------------------------------------------------------------------------------------------------------------------------

def load_overrides(path=OVERRIDES_PATH):
    if not os.path.exists(path):
        return pl.DataFrame(schema={"Track": pl.Utf8, "Level": pl.Int64, "Override": pl.Float64})
    return (
        pl.read_csv(path, schema={"Track": pl.Utf8, "Level": pl.Int64, "Rating": pl.Float64})
        .drop_nulls("Rating")
        .rename({"Rating": "Override"})
    )


def track_ratings(runs_df, votes_df):
    # Rating per track: override if set, else median vote, else the flat level
    # (votes come only from riders who passed, so an unvoted track just hasn't been rated yet)
    return (
        runs_df.select("Track", "Level").unique()
        .join(votes_df, on=["Track", "Level"], how="left")
        .with_columns(
            pl.col("Votes").list.len().fill_null(0).alias("VoteCount"),
            pl.col("Votes").list.median().alias("MedianVote"),
        )
        .join(load_overrides(), on=["Track", "Level"], how="left")
        .with_columns(
            pl.coalesce("Override", "MedianVote", pl.col("Level").cast(pl.Float64)).alias("TrackRating")
        )
        .select("Track", "Level", "VoteCount", "TrackRating")
    )


# Track Medians
# --------------------------------------------------------------------------------------------------------------------------------------------------------------------

def track_medians(runs_df):
    # Fault medians are pulled toward the level median so 1-4 run tracks don't swing wildly; time medians stay per track since track lengths differ too much to share
    level_faults = runs_df.group_by("Level").agg(pl.col("Faults").median().alias("LevelMedianFaults"))
    return (
        runs_df.group_by("Track", "Level")
        .agg(
            pl.len().alias("Runs"),
            pl.col("Faults").median().alias("RawMedianFaults"),
            pl.col("Time").median().alias("MedianTime"),
        )
        .join(level_faults, on="Level")
        .with_columns(
            (
                (pl.col("Runs") * pl.col("RawMedianFaults") + FAULT_MEDIAN_PRIOR_RUNS * pl.col("LevelMedianFaults"))
                / (pl.col("Runs") + FAULT_MEDIAN_PRIOR_RUNS)
            ).alias("MedianFaults")
        )
        .select("Track", "Level", "MedianFaults", "MedianTime")
    )


# Run Scaling
# --------------------------------------------------------------------------------------------------------------------------------------------------------------------

assert all(bonus > 0 for _, bonus in ZERO_FAULT_BONUS), "ZERO_FAULT_BONUS must be positive, or 0f could score below 1f"
assert all(0 <= cap < 1 for _, cap in FAULT_CAP), "FAULT_CAP shares must be between 0 and 1"


def fault_cap(track_rating):
    # This track's FAULT_CAP share, flat past the table's ends
    if track_rating <= FAULT_CAP[0][0]:
        return FAULT_CAP[0][1]
    if track_rating >= FAULT_CAP[-1][0]:
        return FAULT_CAP[-1][1]
    return interpolate(track_rating, FAULT_CAP)


def fault_multiplier(faults, median_faults, track_rating):
    # Share of the track's worth a run keeps for its faults: 1.0 at the median, never past 1 +- the track's cap
    if faults == 0:
        return 1 + fault_cap(track_rating)
    return 1 + fault_cap(track_rating) * math.tanh(FAULT_STEEPNESS * math.log(median_faults / faults))


def zero_fault_shift(faults, median_faults, track_rating):
    # Levels added for a flawless run, fading to 0 by ZERO_FAULT_TAPER of the track's median faults
    bonus = interpolate(min(max(track_rating, ZERO_FAULT_BONUS[0][0]), ZERO_FAULT_BONUS[-1][0]), ZERO_FAULT_BONUS)
    return max(0.0, 1 - faults / (ZERO_FAULT_TAPER * median_faults)) * bonus


def time_scaler(time, median_time):
    # Level shift of at most +-TIME_SHIFT_MAX; kept weak since faults and time are correlated
    return TIME_SHIFT_MAX * max(-1.0, (median_time - time) / median_time)


def run_level(track_rating, faults, median_faults, time, median_time):
    # The level a run is scored at: the track's rating, nudged by time and raised for near-flawless runs. Other faults act on points instead
    return track_rating + zero_fault_shift(faults, median_faults, track_rating) + time_scaler(time, median_time)


def run_score(track_rating, faults, median_faults, time, median_time):
    # Points for one run: the worth of its level, scaled by its faults
    return level_scaler(run_level(track_rating, faults, median_faults, time, median_time)) * fault_multiplier(faults, median_faults, track_rating)


def add_run_scores(runs_df, votes_df=None):
    # Scores every row in the runs dataframe, adding TrackRating, RunLevel and RunScore columns
    if votes_df is None:
        votes_df = track_votes()

    return (
        runs_df.join(track_ratings(runs_df, votes_df), on=["Track", "Level"], how="left")
        .join(track_medians(runs_df), on=["Track", "Level"], how="left")
        .with_columns(
            pl.struct(["TrackRating", "Faults", "MedianFaults", "Time", "MedianTime"])
            .map_elements(
                lambda r: run_level(r["TrackRating"], r["Faults"], r["MedianFaults"], r["Time"], r["MedianTime"]),
                return_dtype=pl.Float64,
            )
            .alias("RunLevel"),
            pl.struct(["TrackRating", "Faults", "MedianFaults", "Time", "MedianTime"])
            .map_elements(
                lambda r: run_score(r["TrackRating"], r["Faults"], r["MedianFaults"], r["Time"], r["MedianTime"]),
                return_dtype=pl.Float64,
            )
            .alias("RunScore"),
        )
    )


# Player Ratings
# --------------------------------------------------------------------------------------------------------------------------------------------------------------------

REFERENCE_WEIGHT = sum(RUN_DECAY**i for i in range(MIN_RUNS))   # ~6.03: the decayed weight of MIN_RUNS runs


assert all(l1 < l2 for (_, l1), (_, l2) in zip(RANKS, RANKS[1:])), "RANKS: levels must rise row by row"
assert all(l1 < l2 and e1 < e2 for (l1, e1), (l2, e2) in zip(ELO_CURVE, ELO_CURVE[1:])), "ELO_CURVE: levels and Elo must both rise row by row"


def elo_from_level(effective_level):
    # Elo read off ELO_CURVE; never under 0
    return max(0, round(interpolate(effective_level, ELO_CURVE)))


def rank_from_level(effective_level):
    # The highest rank whose starting level has been reached, plus its tier ("Champ II"); anyone under the first row gets the first rank's lowest tier.
    # Tiers split each rank's level span evenly; the open-ended top rank is a single rank with no tiers
    i = max([0] + [i for i, (_, level) in enumerate(RANKS) if level <= effective_level])
    rank, start = RANKS[i]
    if i == len(RANKS) - 1:
        return rank
    tier = min(max(int((effective_level - start) / (RANKS[i + 1][1] - start) * len(RANK_TIERS)), 0), len(RANK_TIERS) - 1)
    return f"{rank} {RANK_TIERS[tier]}"


def player_scores(runs_df, votes_df=None):
    # Every run, best first with osu-style decay, summed into a PlayerScore, then effective level, Elo and Rank.
    # Everyone gets an Elo and a Rank; the caller decides who is ranked (MIN_RUNS)
    return (
        add_run_scores(runs_df, votes_df)
        .sort("RunScore", descending=True)
        .with_columns(pl.int_range(pl.len()).over("Player").alias("RunRank"))
        .group_by("Player")
        .agg(
            pl.len().alias("Runs"),
            (pl.col("RunScore") * RUN_DECAY ** pl.col("RunRank")).sum().alias("PlayerScore"),
        )
        .with_columns(
            (pl.col("PlayerScore") / REFERENCE_WEIGHT)
            .map_elements(level_from_worth, return_dtype=pl.Float64)
            .alias("EffectiveLevel")
        )
        .with_columns(
            pl.col("EffectiveLevel").map_elements(elo_from_level, return_dtype=pl.Int64).alias("Elo"),
            pl.col("EffectiveLevel").map_elements(rank_from_level, return_dtype=pl.Utf8).alias("Rank"),
        )
        .sort("PlayerScore", descending=True)
    )
