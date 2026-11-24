"""
THE START BUTTON
================
This is the one file you run to update everything (type "python driver.py" in a terminal in this folder). In order, it:
  1. loads every run from the two run files (see points_calculator.py);
  2. downloads the latest votes from the track rating sheet (see rating_sheet.py);
  3. scores everything and writes three spreadsheet files you can open in Excel or Google Sheets:
       output/player_elo.csv    - every player: Place, Player, Rank, Elo, Level (effective level), Runs, Ranked, TotalPoints, PointsRank
       output/top_runs.csv      - the 25 highest-scoring runs: Rank, Player, Track, Faults, Points
       data/track_ratings.csv   - every track's votes and the rating it's scored at: Track, Level, VoteCount, MinRating, MaxRating, Rating
  4. rebuilds index.html, the leaderboard page (see build_site.py).
"""

import polars as pl   # The table library that reads, sorts and writes the spreadsheet files

import points_calculator as pc
from build_site import SITE_OUTPUT, build_site
from rating_sheet import fetch_sheet, track_votes


# Where the three spreadsheet files are saved
ELO_OUTPUT = "output/player_elo.csv"
TOP_RUNS_OUTPUT = "output/top_runs.csv"
TOP_RUNS_COUNT = 25                # How many runs go in the top runs file
TRACK_RATINGS_OUTPUT = "data/track_ratings.csv"


def player_elo(runs_df, votes_df=None):
    # The Elo board as a table. Everyone gets an Elo and a rank, but only players with at least 7 runs (MIN_RUNS) get a numbered place.
    # Players with fewer runs are still listed, in Elo order, with "Ranked" set to false and no place number
    ranked = pl.col("Runs") >= pc.MIN_RUNS
    return (
        pc.player_scores(runs_df, votes_df)
        .with_columns(ranked.alias("Ranked"))
        .sort(["Elo", "PlayerScore"], descending=True)   # Highest Elo first; on a tie in Elo, the higher exact score goes first
        .with_columns(pl.when(ranked).then(ranked.cast(pl.Int64).cum_sum()).alias("Place"))   # Number the ranked players 1, 2, 3... skipping unranked ones
        .select("Place", "Player", "Rank", "Elo", pl.col("EffectiveLevel").round(2).alias("Level"), "Runs", "Ranked",
                pl.col("TotalPoints").round().cast(pl.Int64), "PointsRank")
    )


def top_runs(runs_df, votes_df=None, count=TOP_RUNS_COUNT):
    # The highest-scoring single runs by anyone, best first
    return (
        pc.add_run_scores(runs_df, votes_df)
        .sort("RunScore", descending=True)
        .head(count)
        .with_columns(pl.int_range(1, pl.len() + 1).alias("Rank"), pl.col("RunScore").round().cast(pl.Int64).alias("Points"))
        .select("Rank", "Player", "Track", "Faults", "Points")
    )


def track_ratings(runs_df, sheet):
    # A table of every track: how many people voted, their lowest and highest vote (blank if nobody voted), and the rating it's
    # actually scored at (a hand-set override if there is one, otherwise the median vote, otherwise its flat level). Hardest first
    votes = track_votes(sheet)
    spread = votes.select(
        "Track",
        "Level",
        pl.col("Votes").list.min().alias("MinRating"),
        pl.col("Votes").list.max().alias("MaxRating"),
    )
    return (
        pc.track_ratings(runs_df, votes)
        .join(spread, on=["Track", "Level"], how="left")
        .with_columns(pl.col("TrackRating").round(2).alias("Rating"))
        .sort(["Rating", "Track"], descending=[True, False])
        .select("Track", "Level", "VoteCount", "MinRating", "MaxRating", "Rating")
    )


# Everything below only happens when this file is run directly (not when another file borrows the functions above)
if __name__ == "__main__":
    runs = pc.load_runs()
    sheet = fetch_sheet()   # Download the rating sheet once and use that same copy for everything
    votes = track_votes(sheet)

    elo = player_elo(runs, votes)
    elo.write_csv(ELO_OUTPUT)
    print(f"Wrote {elo.height} players ({elo['Ranked'].sum()} ranked) to {ELO_OUTPUT}")

    best = top_runs(runs, votes)
    best.write_csv(TOP_RUNS_OUTPUT)
    print(f"Wrote top {best.height} runs to {TOP_RUNS_OUTPUT}")

    ratings = track_ratings(runs, sheet)
    ratings.write_csv(TRACK_RATINGS_OUTPUT)
    print(f"Wrote {ratings.height} track ratings to {TRACK_RATINGS_OUTPUT}")

    build_site(runs, votes)
    print(f"Wrote the leaderboard page to {SITE_OUTPUT}")
