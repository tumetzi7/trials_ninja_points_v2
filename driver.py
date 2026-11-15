import polars as pl

import points_calculator as pc
from democratic_ratings import track_votes


# Writes three CSVs:
#   output/player_elo.csv - Every player's rank and Elo: Place, Player, Rank, Elo, Level (effective level), Runs, Ranked
#   output/top_runs.csv - The best runs by points: Rank, Player, Track, Faults, Points
#   data/track_ratings.csv - Every track's vote spread and rating as scored: Track, Level, VoteCount, MinRating, MaxRating, AvgRating, DemocraticRating

# Usage: python driver.py

ELO_OUTPUT = "output/player_elo.csv"
TOP_RUNS_OUTPUT = "output/top_runs.csv"
TOP_RUNS_COUNT = 10
TRACK_RATINGS_OUTPUT = "data/track_ratings.csv"


def player_elo(runs_df, votes_df=None):
    # Everyone gets an Elo and a Rank (Bronze to SSL); players under MIN_RUNS are listed as unranked (provisional, no Place)
    ranked = pl.col("Runs") >= pc.MIN_RUNS
    return (
        pc.player_scores(runs_df, votes_df)
        .with_columns(ranked.alias("Ranked"))
        .sort(["Elo", "PlayerScore"], descending=True)   # Everyone in Elo order; unranked players sit where their Elo puts them
        .with_columns(pl.when(ranked).then(ranked.cast(pl.Int64).cum_sum()).alias("Place"))   # Place counts ranked players only
        .select("Place", "Player", "Rank", "Elo", pl.col("EffectiveLevel").round(2).alias("Level"), "Runs", "Ranked")
    )


def top_runs(runs_df, votes_df=None, count=TOP_RUNS_COUNT):
    # The highest-scoring individual runs across all players
    return (
        pc.add_run_scores(runs_df, votes_df)
        .sort("RunScore", descending=True)
        .head(count)
        .with_columns(pl.int_range(1, pl.len() + 1).alias("Rank"), pl.col("RunScore").round().cast(pl.Int64).alias("Points"))
        .select("Rank", "Player", "Track", "Faults", "Points")
    )


def track_ratings(runs_df, votes_df):
    # Vote spread per track (blank if nobody voted) beside the rating used for scoring
    # (override, else median sheet vote, else flat level), hardest first
    spread = votes_df.select(
        "Track",
        "Level",
        pl.col("Votes").list.min().alias("MinRating"),
        pl.col("Votes").list.max().alias("MaxRating"),
        pl.col("Votes").list.mean().round(2).alias("AvgRating"),
    )
    return (
        pc.track_ratings(runs_df, votes_df)
        .join(spread, on=["Track", "Level"], how="left")
        .with_columns(pl.col("TrackRating").round(2).alias("DemocraticRating"))
        .sort(["DemocraticRating", "Track"], descending=[True, False])
        .select("Track", "Level", "VoteCount", "MinRating", "MaxRating", "AvgRating", "DemocraticRating")
    )


if __name__ == "__main__":
    runs = pc.load_runs()
    votes = track_votes()   # Fetched once and shared by both outputs

    elo = player_elo(runs, votes)
    elo.write_csv(ELO_OUTPUT)
    print(f"Wrote {elo.height} players ({elo['Ranked'].sum()} ranked) to {ELO_OUTPUT}")

    best = top_runs(runs, votes)
    best.write_csv(TOP_RUNS_OUTPUT)
    print(f"Wrote top {best.height} runs to {TOP_RUNS_OUTPUT}")

    ratings = track_ratings(runs, votes)
    ratings.write_csv(TRACK_RATINGS_OUTPUT)
    print(f"Wrote {ratings.height} track ratings to {TRACK_RATINGS_OUTPUT}")
