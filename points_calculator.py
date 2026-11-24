"""
THE SCORING
===========
This file decides how many points every run is worth, and turns each player's runs into an Elo and a rank.

The short version, start to finish:
  1. Every track gets a difficulty rating (like 8.4), from the community vote sheet or a hand-set override.
  2. A median pass on that track is worth a set number of points, and harder tracks are worth a lot more (each level roughly doubles).
  3. That's adjusted for how cleanly the run was ridden: fewer faults than most riders = more points, more faults = fewer.
     A 0f run gets a big extra boost, scoring as if the track were rated higher.
  4. A player's runs are added up two ways:
       - Elo board: best run first, and each run after counts a bit less than the one above it, so your best runs decide your Elo.
       - Total points board: every run's points simply added together.
  5. The Elo score is turned into an "effective level", then an Elo number and a rank (Iron, Bronze ... Mythic).
     The total is turned into a gem rank (Quartz, Amber ... Obsidian).

Everything you might want to tune sits in the CONSTANTS section right below. The rest of the file is the machinery that uses them.
The leaderboard page has its own copy of this scoring (in site/template.html), so a change to how scoring works must be made in both places.

A few words that come up a lot:
  - "Median": the middle value. If 9 riders passed a track, the median faults is what the 5th-cleanest rider got. Half did better, half worse.
    It's used instead of an average so one disastrous 400-fault run can't drag a track's "typical run" around.
  - "Rating": a track's difficulty, like 8.4. "Level" usually means the whole-number ninja level the game files it under (8).
  - "Effective level": a player's overall skill expressed as a track level. An effective level of 8.5 means your runs add up to
    what a rider who passes level 8.5 tracks at median would get.
"""

import math
import os

import polars as pl   # The table library: it loads the CSV files and does the sorting, grouping and adding up

from rating_sheet import track_votes


# CONSTANTS
# --------------------------------------------------------------------------------------------------------------------------------------------------------------------
# These are the knobs. Each one is explained where it's set.

# How the Elo board adds up a player's runs.
# Your runs are sorted best first. The best counts in full, the 2nd counts 87.5% of its points, the 3rd 87.5% of 87.5%, and so on.
# By your 10th run it's down to 30%, the 20th 8%, the 50th 0.1%. So your best 20 or so runs decide your Elo: a handful of hard
# passes beats any number of easy ones, and padding your account with extra easy runs adds almost nothing.
RUN_DECAY = 0.875
MIN_RUNS = 7                       # You need at least 7 runs to get a place on the Elo board (below that you're shown as "unranked")
# Where effective levels land. Your decayed score is compared with what 12 median passes at one level would add up to. So "effective
# level 8" means your best runs add up to about 12 median level 8 passes. Raising it pushes everyone's level down, lowering it pushes them up.
# It changes where players land (12 puts 7 riders in Mythic), never who's ahead of whom
REFERENCE_RUNS = 12
MAX_COUNTED_RUNS = 0               # Only count each player's best this-many runs toward Elo. 0 means count them all (they fade out anyway)

# The Elo ranks: (rank name, effective level where it starts). One rank per whole level: a level 7 rider is Champ, level 8 Grand Champ.
# The last rank has no ceiling and isn't split into I / II / III
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
    ("Divine",       9 + 5 / 6),   # 3000 Elo. Hidden: nobody holds it, and it's left out of the page's rank guide and the README
]

# Each rank (except the top one) is split into three equal parts, I being the lowest: Champ I starts at effective level 7.0,
# Champ II at 7.33 and Champ III at 7.67
RANK_TIERS = ["I", "II", "III"]

# The total points ranks: gems. A twin of the Elo ladder for the "grind" board, where every run's points are simply added up.
# Nine gems split I / II / III like the Elo ranks, with Obsidian alone at the top. Quartz lines up with Iron and Pearl with Mythic.
# Each number is the total points where that division starts. They're fixed numbers, so your gem only changes when your own total does,
# never because someone else got better. Points per level roughly double (a median level 8 pass is 5,000, level 9 is 10,000), so the
# gaps between gems have to widen as you go up, the same way each Elo rank needs a harder level.
# For scale: a median pass on every track in the game adds up to about 1.18 million, and every level 7, 8 and 9 track about 760,000
POINTS_RANKS = [
    ("Quartz I",              0), ("Quartz II",         100), ("Quartz III",         200),   # Inside each gem the divisions are evenly
    ("Amber I",             400), ("Amber II",          800), ("Amber III",        1_200),   # spaced: 100 apart for Quartz, 400 for Amber,
    ("Topaz I",           1_600), ("Topaz II",        2_400), ("Topaz III",        3_200),   # 800 for Topaz, 2,000 for Aquamarine,
    ("Aquamarine I",      4_000), ("Aquamarine II",   6_000), ("Aquamarine III",   8_000),   # 5,000 for Amethyst, 10,000 for Sapphire
    ("Amethyst I",       10_000), ("Amethyst II",    15_000), ("Amethyst III",    20_000),
    ("Sapphire I",       25_000), ("Sapphire II",    35_000), ("Sapphire III",    45_000),
    ("Emerald I",        60_000), ("Emerald II",     80_000), ("Emerald III",    110_000),
    ("Ruby I",          150_000), ("Ruby II",       225_000), ("Ruby III",       350_000),
    ("Pearl I",         600_000), ("Pearl II",      800_000), ("Pearl III",    1_000_000),
    ("Obsidian",      1_250_000),   # Roughly a player with every level 8 and 9 passed, a level 8 0f and five level 7 0fs, plus a buffer
]

# Turning an effective level into an Elo number: (effective level, Elo at that level). In between two rows it goes in a straight line,
# so effective level 7.5 is 1950 Elo. Each rank is 300 Elo wide up to Champ. Grand Champ is 400 wide and Mythic wider still, so the very
# top players spread out instead of bunching together. Past level 10 it keeps climbing at the last row's rate (600 Elo per level)
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

MAX_FAULTS = 499                   # The game's limit: 500 faults is a fault-out, so no real pass can have more than 499
MAX_TIME = (30 * 60 * 1000) - 1    # The game's time limit, 29:59.999. Times are stored in milliseconds (1 second = 1,000)

# How much a median pass is worth at each level: (level, how many times the level below it's worth).
# A "2" on level 7's row means a median level 8 pass is worth 2 median level 7 passes. These multiply up to (median pass worth):
#   level 1 = 25 points, 2 = 50, 3 = 100, 4 = 200, 5 = 500, 6 = 1,000, 7 = 2,500, 8 = 5,000, 9 = 10,000, 10 = 20,000.
# Between whole levels it climbs smoothly, so an 8.5 track is worth about 7,070. The steps are only 2 to 2.5 (not 10 or 100) so that
# lower-level runs still earn real points instead of rounding to nothing
LEVEL_STEPS = [
    (1,    2),
    (2,    2),
    (3,    2),
    (4,    2.5),
    (5,    2),
    (6,    2.5),
    (7,    2),
    (8,    2),
    (9,    2),
]
# How much of a level 9 track's decimals count. 1 = all of it: a 9.5 track is scored as a 9.5, and each 0.1 adds about 7%.
# A smaller number squashes level 9 closer together (0.75 would score a 9.5 like a 9.375)
TOP_RATING_SPREAD = 1.0


# FAULT & TIME SCALING
# --------------------------------------------------------------------------------------------------------------------------------------------------------------------
'''
How faults change a run's points.

Faults move a run's points up or down by a percentage, compared with the track's median faults:
  - a run with exactly the median faults keeps exactly the track's worth;
  - half the median faults earns as much as double the median loses (so 25f vs a 50f median is as good as 100f is bad);
  - nothing ever goes past the track's cap (FAULT_CAP below). Past a point, a few faults either way stop mattering, because
    a low-fault run on a hard, inconsistent track is partly luck.
  The formula, for the curious: points = track worth x (1 + cap x tanh(FAULT_STEEPNESS x ln(median faults / faults))).
  "tanh" is just a smooth S-curve that starts at 0 and levels off at 1, so the effect grows quickly near the median and flattens toward the cap.

0f runs are special. On top of that, a 0f is scored as if the track were rated ZERO_FAULT_BONUS levels harder.
A 1f run only keeps LOW_FAULT_SHARE (63%) of that bonus, so 0f to 1f is a big drop: the "0f cliff". After 1f the leftover bonus fades
away evenly and is gone by LOW_FAULT_REACH (20%) of the track's median faults, but never before 2f.
Example on a track with a 100-fault median: 1f keeps 63% of the bonus, 5f 50%, 10f 33%, and 20f none.
'''

# The most faults can add or take away, as a share of the run's points, by track rating: (rating, share).
# Lower levels get a bigger range because those tracks are consistent, so riding them cleaner genuinely shows skill.
# At level 9 it's only 5%: the hardest tracks are so inconsistent that low faults are mostly luck, so the track's rating decides.
# That means a pass on a 9.4 beats a pass on a 9.25 unless the 9.25 run was a 0f or very low-fault run
FAULT_CAP = [
    (1,    0.45),
    (2,    0.40),
    (3,    0.35),
    (4,    0.30),
    (5,    0.25),
    (6,    0.20),
    (7,    0.15),
    (8,    0.10),
    (9,    0.05),
]
FAULT_STEEPNESS = 1.3              # How quickly a run heads toward the cap as it beats the median. Higher spreads runs near the median further apart
# The 0f bonus, by track rating: (rating, how many levels harder a 0f run is scored as). Straight lines in between
ZERO_FAULT_BONUS = [
    (5,    2.05),                  # Level 5 and below: a level 5 0f scores like a median 7.05 pass. Not bigger, since low-level 0fs are common
    (6,    1.85),                  # A level 6 0f scores like a median level 7.85 pass
    (7,    1.5),                   # A level 7 0f scores like a median level 8.5 pass
    (8,    1.3),                   # Level 8 and up: smallest, since points already climb steeply here. Puts the level 8 0fs (Vicious, King Pin 3)
    (10,   1.3),                   # just under the Claymore passes
]
# A 1f run keeps 63% of the 0f bonus. That gap is the "0f cliff": a 0f ends up worth 1.38 times a 1f from level 8 up, 1.45 times at
# level 7 and 1.94 times at level 5
LOW_FAULT_SHARE = 0.63
# ...and what's left fades away evenly from 1f to nothing at 20% of the track's median faults (20f on a 100-fault-median track), never
# sooner than 2f. It fades slowly on purpose, so the only steep drop is 0f to 1f
LOW_FAULT_REACH = 0.20
# A track with only a few passes has a shaky median (3 runs isn't much to go on). So each track's median faults is blended with the
# median of all tracks at that level, as if 5 extra runs at the level median had been ridden there. Tracks with lots of runs barely move
FAULT_MEDIAN_PRIOR_RUNS = 5

# Time. Being faster or slower than the track's median time nudges the level a run is scored at, by at most 0.01 of a level.
# Half the median time = +0.005 levels; slower loses the same way. It's kept tiny on purpose: fast runs usually also have fewer faults,
# which already counts, and time is mostly a tiebreaker
TIME_SHIFT_MAX = 0.01

# Track ratings come from the median vote on the rating sheet (see rating_sheet.py). A track nobody voted on counts at its flat level
# (an unvoted level 7 track is exactly 7.0). This file holds hand-set ratings, which beat the votes for any track listed
OVERRIDES_PATH = "data/track_rating_overrides.csv"


# The shape of a run once loaded: who, which track, its level, faults and time (in milliseconds)
RUNS_SCHEMA = {
    "Player": pl.Utf8,
    "Track": pl.Utf8,
    "Level": pl.Int64,
    "Faults": pl.Int64,
    "Time": pl.Float64,
}

# Extra-checkpoint versions of tracks don't count, only full tracks. They're spotted by name: a + or ++ (Anomaly [+CPs], Hattusa ++CP,
# Whitespire (+CPs), Steel Wave +) or "50 cps" (Deviant [50cps], Hattusa 50 Cps Fix). No full track has a + in its name
EXTRA_CP_PATTERN = r"(?i)\+|50\s*cps"


# Where the run data comes from
EXPORT_PATH = "data/ninja_runs.csv"           # The game export: every player's best run on every ninja track, all levels
CURATED_PATH = "data/runs_curated.csv"        # The hand-collected list of level 7 to 9 passes the rating sheet is built on
TRACK_LEVELS_PATH = "data/track_levels.csv"   # Hand fixes for tracks the game files under the wrong level (Incendiary is a 7, not a 4)
EXCLUDED_PATH = "data/excluded_runs.csv"      # Junk runs to throw out, such as bug passes with impossible times
# If both files list a track with the same name, the curated file's level wins, but only when the two levels are at most 1 apart.
# Further apart than that, it's a different track that happens to share a name (the export's level 2 Halcyon isn't the curated level 7 one)
CURATED_LEVEL_REACH = 1
CLAN_TAG_PATTERN = r"^\[[^\]]*\]\s*"          # Clan tags are stripped so names match: "[QK] RandallQK" in the curated file is "RandallQK" in the export
CURATED_RENAMES = {                           # Players whose curated-file name is a different account name in the export
    "del230330031001": "del2303300310017591714",   # A deleted account, shown cut short in the curated file
    "MayaQK": "TrialsEloReaper",                   # Same rider, now on this account
}
TRACK_RENAMES = {                             # The same track uploaded twice under two names, merged into one. Each player keeps their better run
    "shyu park [FIX*]": "SHYU PARK",               # The fixed re-upload of SHYU PARK
}


def load_track_levels(path=TRACK_LEVELS_PATH):
    # Reads the hand-fixed track levels (an empty list if the file doesn't exist)
    if not os.path.exists(path):
        return pl.DataFrame(schema={"Track": pl.Utf8, "FixedLevel": pl.Int64})
    return pl.read_csv(path, schema={"Track": pl.Utf8, "Level": pl.Int64}).rename({"Level": "FixedLevel"})


def load_export(path=EXPORT_PATH):
    # Reads the game export and tidies it up:
    #  - a player with no username is shown as "Player" plus the start of their account id;
    #  - two different tracks with the same name and level get their track id added to the name, so their runs don't get mixed together;
    #  - merged track names (TRACK_RENAMES) and hand-fixed levels (track_levels.csv) are applied
    export = pl.read_csv(path, encoding="utf8-lossy")
    collide = pl.col("track id").n_unique().over("track name", "ninja level") > 1
    return (
        export.select(
            pl.coalesce("username", pl.lit("Player ") + pl.col("user id").str.slice(0, 8)).alias("Player"),
            pl.when(collide).then(pl.format("{} #{}", "track name", "track id")).otherwise("track name")
            .replace(TRACK_RENAMES).alias("Track"),
            pl.col("ninja level").alias("Level"),
            pl.col("faults").alias("Faults"),
            pl.col("time").cast(pl.Float64).alias("Time"),
        )
        .join(load_track_levels(), on="Track", how="left")
        .with_columns(pl.coalesce("FixedLevel", "Level").alias("Level"))
        .drop("FixedLevel")
    )


def load_excluded(path=EXCLUDED_PATH):
    # Reads the junk-run list. A run is only thrown out if every detail matches (player, track, level, faults and time),
    # so a later, real run by the same player on the same track still counts
    schema = {k: RUNS_SCHEMA[k] for k in ["Player", "Track", "Level", "Faults", "Time"]}
    if not os.path.exists(path):
        return pl.DataFrame(schema=schema)
    return pl.read_csv(path, schema_overrides=schema).select(list(schema))


def load_runs(export_path=EXPORT_PATH, curated_path=CURATED_PATH):
    # Puts both run files together into one list, one run per player per track.
    #  - Every run in either file counts. Where a player has a run on the same track in both, their better one is kept
    #    (fewest faults, then fastest time), since the export has newer PBs and the curated file has passes the export is missing.
    #  - A track the curated file lists takes its level from there (the export files some a level off, like Sinister),
    #    but only when the levels are within CURATED_LEVEL_REACH of each other (see above).
    #  - Junk runs are thrown out first, so if a player has another real run on that track, that one takes its place
    export = load_export(export_path)
    curated = pl.read_csv(curated_path, schema=RUNS_SCHEMA).with_columns(
        pl.col("Player").str.replace(CLAN_TAG_PATTERN, "").replace(CURATED_RENAMES),
        pl.col("Track").replace(TRACK_RENAMES),
    )
    curated_levels = curated.select("Track", pl.col("Level").alias("CuratedLevel")).unique()
    same_track = (pl.col("CuratedLevel") - pl.col("Level")).abs() <= CURATED_LEVEL_REACH
    runs = (
        pl.concat([
            export.join(curated_levels, on="Track", how="left")
            .with_columns(pl.when(same_track).then("CuratedLevel").otherwise("Level").alias("Level"))
            .drop("CuratedLevel"),
            curated,
        ])
        .join(load_excluded(), on=["Player", "Track", "Level", "Faults", "Time"], how="anti")   # Drop the junk runs
        .sort("Faults", "Time")                                                                 # Cleanest, then fastest, first...
        .unique(["Player", "Track", "Level"], keep="first", maintain_order=True)                # ...so keeping the first keeps each player's best
    )
    return check_runs(runs, f"{export_path} or {curated_path}")


def check_runs(runs, source):
    # Safety check. Every row is meant to be a real pass, so a blank, negative faults, 500+ faults or an impossible time can only be a
    # typing mistake in the data. Rather than quietly score a broken run, it stops and lists the bad rows so they can be fixed.
    # It also drops the extra-checkpoint versions of tracks here
    bad = runs.filter(
        pl.any_horizontal(pl.all().is_null())
        | ~pl.col("Faults").is_between(0, MAX_FAULTS)
        | ~((pl.col("Time") > 0) & (pl.col("Time") <= MAX_TIME))
    )
    if bad.height:
        raise ValueError(
            f"{bad.height} rows in {source} break the rules (no blanks, 0 to {MAX_FAULTS} faults, "
            f"time above 0 and under 30:00):\n{bad}"
        )
    return runs.filter(~pl.col("Track").str.contains(EXTRA_CP_PATTERN))


# Level Worth
# --------------------------------------------------------------------------------------------------------------------------------------------------------------------
# Turns a track rating into how many points a median pass on it is worth, following LEVEL_STEPS

def interpolate(x, points):
    # Reads a value off a table of (x, y) rows by drawing straight lines between the rows. Used all over this file:
    # e.g. with ELO_CURVE, effective level 7.5 sits halfway between (7, 1800) and (8, 2100), so it gives 1950.
    # Past either end of the table, the first or last line just keeps going
    i = 1
    while i < len(points) - 1 and x > points[i][0]:
        i += 1
    (x0, y0), (x1, y1) = points[i - 1], points[i]
    return y0 + (y1 - y0) * (x - x0) / (x1 - x0)


# A safety check on LEVEL_STEPS: one row per level, none skipped, and every step must make the next level worth more
assert all(
    row[0] == LEVEL_STEPS[0][0] + i and row[1] > 1 for i, row in enumerate(LEVEL_STEPS)
), "LEVEL_STEPS needs one row per level, none skipped, each step above 1"

# Behind the scenes, worth is stored as a logarithm ("ln"). That's just a way of turning "multiply by 2 each level" into "add the same
# amount each level", which makes the smooth climb between whole levels a straight line and keeps the maths simple
LEVEL_LOG_WORTH = [(LEVEL_STEPS[0][0], 0.0)]
for level, step in LEVEL_STEPS:
    LEVEL_LOG_WORTH.append((level + 1, LEVEL_LOG_WORTH[-1][1] + math.log(step)))

# Sets the size of the numbers: a median level 8 pass is worth 5,000 points. Purely cosmetic: making it 1 would shrink every score
# by the same amount and nobody's position would change
POINTS_AT_LEVEL_8 = 5000
POINTS_SCALE = POINTS_AT_LEVEL_8 / math.exp(interpolate(8, LEVEL_LOG_WORTH))


def level_scaler(level):
    # How many points a median pass on a track of this rating is worth (level 8 = 5,000, 8.5 = about 7,070, 9 = 10,000)
    return POINTS_SCALE * math.exp(interpolate(level, LEVEL_LOG_WORTH))


def level_from_worth(worth):
    # The reverse: given a number of points, which track rating would a median pass need to be on to be worth that much.
    # This is how a player's score becomes an "effective level"
    return interpolate(math.log(worth / POINTS_SCALE), [(log_worth, level) for level, log_worth in LEVEL_LOG_WORTH])


# Track Ratings
# --------------------------------------------------------------------------------------------------------------------------------------------------------------------

def load_overrides(path=OVERRIDES_PATH):
    # Reads the hand-set track ratings (an empty list if the file doesn't exist)
    if not os.path.exists(path):
        return pl.DataFrame(schema={"Track": pl.Utf8, "Level": pl.Int64, "Override": pl.Float64})
    return (
        pl.read_csv(path, schema={"Track": pl.Utf8, "Level": pl.Int64, "Rating": pl.Float64})
        .drop_nulls("Rating")
        .rename({"Rating": "Override"})
    )


def track_ratings(runs_df, votes_df):
    # Gives every track its difficulty rating, in this order of preference:
    #   1. a hand-set rating from the overrides file;
    #   2. otherwise the median of the votes on the rating sheet;
    #   3. otherwise the track's flat level (only riders who passed a track vote on it, so no votes just means it hasn't been rated yet)
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
    # Each track's "typical run": its median faults and median time, which every run on it is compared against.
    # Faults: blended with the level's median as if 5 extra runs were ridden there (FAULT_MEDIAN_PRIOR_RUNS), so a track with only
    # 1 to 4 passes doesn't swing wildly on one rider's run. Time: kept per track, because track lengths differ too much to blend
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
# Scoring a single run. In two parts:
#   1. the LEVEL the run is scored at: the track's rating, plus the 0f bonus if it earned one, plus or minus a tiny bit for time;
#   2. the POINTS: what a median pass at that level is worth, times the fault adjustment

# Safety checks on the settings: a 0f bonus of zero or less could make a 0f score below a 1f, and a fault cap of 100% or more
# could push a run's points to zero or below
assert all(bonus > 0 for _, bonus in ZERO_FAULT_BONUS), "ZERO_FAULT_BONUS must be positive, or 0f could score below 1f"
assert all(0 <= cap < 1 for _, cap in FAULT_CAP), "FAULT_CAP shares must be between 0 and 1"


def fault_cap(track_rating):
    # The most faults can move a run on this track (from FAULT_CAP). Below level 1 it stays at level 1's, above level 9 at level 9's
    if track_rating <= FAULT_CAP[0][0]:
        return FAULT_CAP[0][1]
    if track_rating >= FAULT_CAP[-1][0]:
        return FAULT_CAP[-1][1]
    return interpolate(track_rating, FAULT_CAP)


def fault_multiplier(faults, median_faults, track_rating):
    # What a run's points are multiplied by for its faults. Exactly 1 at the median; above 1 for cleaner runs, below 1 for messier ones;
    # never further than the track's cap. A 0f gets the full cap (e.g. x1.10 at level 8)
    if faults == 0:
        return 1 + fault_cap(track_rating)
    return 1 + fault_cap(track_rating) * math.tanh(FAULT_STEEPNESS * math.log(median_faults / faults))


def zero_fault_shift(faults, median_faults, track_rating):
    # The extra levels a 0f (or near-0f) run is scored at: the full ZERO_FAULT_BONUS for a 0f, a drop to 63% of it at 1f,
    # then fading evenly to nothing by 20% of the track's median faults (2f at the earliest). Anything past that gets no bonus
    bonus = interpolate(min(max(track_rating, ZERO_FAULT_BONUS[0][0]), ZERO_FAULT_BONUS[-1][0]), ZERO_FAULT_BONUS)
    if faults == 0:
        return bonus
    fade_end = max(LOW_FAULT_REACH * median_faults, 2)
    return LOW_FAULT_SHARE * max(0.0, (fade_end - faults) / (fade_end - 1)) * bonus


def time_scaler(time, median_time):
    # The tiny level nudge for time: up to +0.01 for being much faster than the median, down to -0.01 for being much slower
    return TIME_SHIFT_MAX * max(-1.0, (median_time - time) / median_time)


def scored_rating(track_rating):
    # The rating a run is scored at. Below level 9 it's just the track's rating. From level 9 up, TOP_RATING_SPREAD can squash the
    # decimals (it's set to 1 right now, so a 9.5 still scores as 9.5)
    if track_rating < 9:
        return track_rating
    whole = math.floor(track_rating)
    return whole + (track_rating - whole) * TOP_RATING_SPREAD


def run_level(track_rating, faults, median_faults, time, median_time):
    # Part 1: the level this run is scored at. The track's rating, plus the 0f bonus if any, plus or minus the time nudge.
    # (Ordinary faults don't change the level; they change the points, in part 2)
    return scored_rating(track_rating) + zero_fault_shift(faults, median_faults, track_rating) + time_scaler(time, median_time)


def run_score(track_rating, faults, median_faults, time, median_time):
    # Part 2: the run's points. What a median pass at its scored level is worth, times its fault adjustment.
    # Example: a 0f on a level 8.0 track is scored at level 9.3 (8.0 + the 1.3 bonus), worth about 12,300, then x1.10 for the 0f = about 13,500
    return level_scaler(run_level(track_rating, faults, median_faults, time, median_time)) * fault_multiplier(faults, median_faults, track_rating)


def add_run_scores(runs_df, votes_df=None):
    # Scores every run in the list. Adds three columns to each: the track's rating, the level the run was scored at, and its points
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
# Turning each player's runs into their Elo, rank, total points and gem

# What 12 runs add up to after the decay (1 + 0.875 + 0.875 x 0.875 + ... twelve times, about 6.4). A player's decayed score is divided
# by this, which turns it into "the worth of one typical run of theirs". That's then read back as a track level: the effective level
REFERENCE_WEIGHT = sum(RUN_DECAY**i for i in range(REFERENCE_RUNS))


# Safety checks on the rank and Elo tables: every row must start higher than the one before
assert all(l1 < l2 for (_, l1), (_, l2) in zip(RANKS, RANKS[1:])), "RANKS: levels must rise row by row"
assert POINTS_RANKS[0][1] == 0 and all(a < b for (_, a), (_, b) in zip(POINTS_RANKS, POINTS_RANKS[1:])), "POINTS_RANKS: gates must start at 0 and rise"
assert all(l1 < l2 and e1 < e2 for (l1, e1), (l2, e2) in zip(ELO_CURVE, ELO_CURVE[1:])), "ELO_CURVE: levels and Elo must both rise row by row"


def elo_from_level(effective_level):
    # An effective level's Elo, read off ELO_CURVE (never below 0)
    return max(0, round(interpolate(effective_level, ELO_CURVE)))


def rank_from_level(effective_level):
    # An effective level's rank, with its division: 7.5 is "Champ II". Anyone below level 1 is Iron I.
    # The top rank has no divisions
    i = max([0] + [i for i, (_, level) in enumerate(RANKS) if level <= effective_level])
    rank, start = RANKS[i]
    if i == len(RANKS) - 1:
        return rank
    tier = min(max(int((effective_level - start) / (RANKS[i + 1][1] - start) * len(RANK_TIERS)), 0), len(RANK_TIERS) - 1)
    return f"{rank} {RANK_TIERS[tier]}"


def points_rank(total_points):
    # A points total's gem: the highest division it has reached (e.g. 300,000 points is "Ruby II")
    return [name for name, start in POINTS_RANKS if start <= total_points][-1]


def level_cap(highest_level_passed):
    # The rank gate: you can't rank above the rank of the hardest level you've passed. Mythic needs a level 9 pass, Grand Champ a
    # level 8 pass, and so on, no matter how many easier tracks you've cleared. So for Elo and rank, a player's effective level is
    # held just under (hardest level passed + 1). Riding lots of tracks still moves you up inside that rank
    return highest_level_passed + 1


def gated_elo(effective_level, highest_level_passed):
    # Elo with the rank gate applied: held at the top of the highest rank your passes allow
    # (2499 for someone whose hardest pass is a level 8, one short of Mythic)
    cap = level_cap(highest_level_passed)
    return elo_from_level(effective_level) if effective_level < cap else elo_from_level(cap) - 1


def gated_rank(effective_level, highest_level_passed):
    # Rank with the rank gate applied: held at the top division of the highest rank your passes allow
    return rank_from_level(min(effective_level, level_cap(highest_level_passed) - 1e-9))


def player_scores(runs_df, votes_df=None):
    # The final step: every player's numbers.
    #   1. Score every run, then sort each player's runs best first.
    #   2. Elo score: add them up with the decay (best in full, each next one 87.5% of the one above).
    #      Total points: add them all up as they are.
    #   3. Effective level: the Elo score divided by REFERENCE_WEIGHT, read back as a track level. Shown on the page as "Level",
    #      without the rank gate, so it can be higher than the rank allows.
    #   4. Elo and rank from the effective level, with the rank gate. Gem rank from the total points.
    # Everyone gets numbers here; who has a numbered place on the Elo board (7+ runs) is decided later
    return (
        add_run_scores(runs_df, votes_df)
        .sort("RunScore", descending=True)
        .with_columns(pl.int_range(pl.len()).over("Player").alias("RunRank"))   # Each run's position in its player's list: 0 = their best
        .group_by("Player")
        .agg(
            pl.len().alias("Runs"),
            pl.col("Level").max().alias("HighestLevel"),
            (pl.col("RunScore") * RUN_DECAY ** pl.col("RunRank"))                 # Best run x 1, 2nd x 0.875, 3rd x 0.875 x 0.875, ...
            .filter((pl.col("RunRank") < MAX_COUNTED_RUNS) if MAX_COUNTED_RUNS else pl.lit(True))
            .sum()
            .alias("PlayerScore"),
            pl.col("RunScore").sum().alias("TotalPoints"),   # The grind board: every run's points, no decay and no limit
        )
        .with_columns(
            (pl.col("PlayerScore") / REFERENCE_WEIGHT)
            .map_elements(level_from_worth, return_dtype=pl.Float64)
            .alias("EffectiveLevel")
        )
        .with_columns(
            pl.struct(["EffectiveLevel", "HighestLevel"])
            .map_elements(lambda r: gated_elo(r["EffectiveLevel"], r["HighestLevel"]), return_dtype=pl.Int64)
            .alias("Elo"),
            pl.struct(["EffectiveLevel", "HighestLevel"])
            .map_elements(lambda r: gated_rank(r["EffectiveLevel"], r["HighestLevel"]), return_dtype=pl.Utf8)
            .alias("Rank"),
            pl.col("TotalPoints").map_elements(points_rank, return_dtype=pl.Utf8).alias("PointsRank"),
        )
        .sort("PlayerScore", descending=True)
    )
