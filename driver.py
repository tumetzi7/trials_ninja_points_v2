import polars as pl

import points_calculator as pc
from build_site import SITE_OUTPUT, build_site
from democratic_ratings import CORRECT_VOTER_LEAN, fetch_sheet, track_votes


# Writes index.html (the leaderboard page, see build_site.py) and three CSVs:
#   output/player_elo.csv - Every player's rank and Elo: Place, Player, Rank, Elo, Level (effective level), Runs, Ranked
#   output/top_runs.csv - The best runs by points: Rank, Player, Track, Faults, Points
#   data/track_ratings.csv - Every track's vote spread and both candidate ratings: Track, Level, VoteCount, MinRating, MaxRating, MedianRating, DemocraticRating

# Usage: python driver.py

ELO_OUTPUT = "output/player_elo.csv"
TOP_RUNS_OUTPUT = "output/top_runs.csv"
TOP_RUNS_COUNT = 25
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


def track_ratings(runs_df, sheet):
    # Raw vote spread per track (blank if nobody voted) beside both candidate ratings, hardest first by the one scoring uses.
    # Both apply the same fallbacks (override, else median vote, else flat level):
    #   MedianRating - median of the raw votes; scored when CORRECT_VOTER_LEAN is off
    #   DemocraticRating - median of the voter-lean-corrected votes; scored when CORRECT_VOTER_LEAN is on
    raw_votes = track_votes(sheet, correct_lean=False)
    spread = raw_votes.select(
        "Track",
        "Level",
        pl.col("Votes").list.min().alias("MinRating"),
        pl.col("Votes").list.max().alias("MaxRating"),
    )
    corrected = pc.track_ratings(runs_df, track_votes(sheet, correct_lean=True)).select(
        "Track", "Level", pl.col("TrackRating").round(2).alias("DemocraticRating")
    )
    scored_by = "DemocraticRating" if CORRECT_VOTER_LEAN else "MedianRating"
    return (
        pc.track_ratings(runs_df, raw_votes)
        .join(spread, on=["Track", "Level"], how="left")
        .join(corrected, on=["Track", "Level"], how="left")
        .with_columns(pl.col("TrackRating").round(2).alias("MedianRating"))
        .sort([scored_by, "Track"], descending=[True, False])
        .select("Track", "Level", "VoteCount", "MinRating", "MaxRating", "MedianRating", "DemocraticRating")
    )


if __name__ == "__main__":
    runs = pc.load_runs()
    sheet = fetch_sheet()   # Fetched once and shared by all three outputs
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

    build_site(runs, votes, elo)
    print(f"Wrote the leaderboard page to {SITE_OUTPUT}")
