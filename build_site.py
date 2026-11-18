import datetime
import json

import polars as pl

import points_calculator as pc


# Writes index.html: a standalone leaderboard page (players, every scored run, per-track leaderboards) with the data baked in.
# Called by driver.py after the CSVs are written; can also be run on its own.

# Usage: python build_site.py

SITE_TEMPLATE = "site/template.html"
SITE_OUTPUT = "index.html"


def site_data(runs_df, votes_df, elo_df):
    scored = pc.add_run_scores(runs_df, votes_df)
    tracks = (
        scored.group_by("Track", "Level")
        .agg(pl.col("TrackRating").first().round(2).alias("Rating"), pl.col("VoteCount").first())
        .sort("Rating", "Track", descending=[True, False])
    )
    return {
        "generated": datetime.date.today().isoformat(),
        "players": elo_df.to_dicts(),
        "runs": scored.select(
            "Player", "Track", "Level", "Faults",
            pl.col("Time").cast(pl.Int64),
            pl.col("RunScore").round().cast(pl.Int64).alias("Points"),
            pl.col("RunLevel").round(2),
        ).to_dicts(),
        "tracks": tracks.to_dicts(),
    }


def build_site(runs_df, votes_df, elo_df, path=SITE_OUTPUT):
    data = json.dumps(site_data(runs_df, votes_df, elo_df), ensure_ascii=False, separators=(",", ":"))
    with open(SITE_TEMPLATE, encoding="utf-8") as f:
        html = f.read().replace("__DATA__", data.replace("</", r"<\/"))   # A "</" inside the JSON would end the script tag
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(html)


if __name__ == "__main__":
    from democratic_ratings import track_votes
    from driver import player_elo

    runs = pc.load_runs()
    votes = track_votes()
    build_site(runs, votes, player_elo(runs, votes))
    print(f"Wrote {SITE_OUTPUT}")
