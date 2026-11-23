import base64
import datetime
import gzip
import json

import polars as pl

import points_calculator as pc


# Writes index.html: a standalone leaderboard page (players, every scored run, per-track leaderboards) with the data baked in.
# Called by driver.py after the CSVs are written; can also be run on its own.

# Usage: python build_site.py

SITE_TEMPLATE = "site/template.html"
SITE_OUTPUT = "index.html"

# The top rank's chip colour (light, dark). Always written, since the page's settings can put anyone in any rank
TOP_RANK_COLOURS = ("#b8002e", "#ff4d6d")


def top_rank_css():
    light, dark = TOP_RANK_COLOURS
    cls = ".r-" + pc.RANKS[-1][0].replace(" ", "-")
    return (
        f'{cls} {{ --rc: {light}; }}\n'
        f'@media (prefers-color-scheme: dark) {{ :root:not([data-theme="light"]) {cls} {{ --rc: {dark}; }} }}\n'
        f':root[data-theme="dark"] {cls} {{ --rc: {dark}; }}\n'
    )


def settings():
    # The scoring constants the page starts from. The page scores every run itself (a port of points_calculator.py),
    # so its settings panel can change any of these live
    return {
        "level_steps": pc.LEVEL_STEPS,
        "top_rating_spread": pc.TOP_RATING_SPREAD,
        "points_at_level_8": pc.POINTS_AT_LEVEL_8,
        "fault_cap": pc.FAULT_CAP,
        "fault_steepness": pc.FAULT_STEEPNESS,
        "zero_fault_bonus": pc.ZERO_FAULT_BONUS,
        "low_fault_share": pc.LOW_FAULT_SHARE,
        "low_fault_reach": pc.LOW_FAULT_REACH,
        "raw_points_step": pc.RAW_POINTS_STEP,
        "raw_points_at_level_1": pc.RAW_POINTS_AT_LEVEL_1,
        "fault_median_prior_runs": pc.FAULT_MEDIAN_PRIOR_RUNS,
        "time_shift_max": pc.TIME_SHIFT_MAX,
        "run_decay": pc.RUN_DECAY,
        "min_runs": pc.MIN_RUNS,
        "max_counted_runs": pc.MAX_COUNTED_RUNS,
        "ranks": pc.RANKS,
        "rank_tiers": pc.RANK_TIERS,
        "elo_curve": pc.ELO_CURVE,
    }


def site_data(runs_df, votes_df):
    # Raw runs only: points, Elo and ranks are worked out in the page from "settings".
    # Runs go out as [player index, track index, faults, time] rows indexing "players" and "tracks",
    # since tens of thousands of runs as named objects would make the page several times larger
    tracks = (
        pc.track_ratings(runs_df, votes_df)
        .rename({"TrackRating": "Rating"})
        .sort("Rating", "Track", descending=[True, False])
    )
    players = runs_df.select(pl.col("Player").unique().sort())
    runs = (
        runs_df.join(players.with_row_index("pi"), on="Player")
        .join(tracks.select("Track", "Level").with_row_index("ti"), on=["Track", "Level"])
        .select("pi", "ti", "Faults", pl.col("Time").cast(pl.Int64))
    )
    assert runs.height == runs_df.height, "every run needs its player and track in the page data"
    return {
        "generated": datetime.date.today().isoformat(),
        "settings": settings(),
        "players": players["Player"].to_list(),
        "tracks": tracks.to_dicts(),
        "runs": runs.rows(),
    }


def build_site(runs_df, votes_df, path=SITE_OUTPUT):
    # The data goes in gzipped and base64-encoded: the page unpacks it, and there's no readable table in the page source.
    # It's still in the page for anyone who decodes it, so put nothing in site_data that shouldn't be public
    data = json.dumps(site_data(runs_df, votes_df), ensure_ascii=False, separators=(",", ":"))
    packed = base64.b64encode(gzip.compress(data.encode("utf-8"), mtime=0)).decode("ascii")
    with open(SITE_TEMPLATE, encoding="utf-8") as f:
        html = f.read().replace("__DATA__", packed)
    html = html.replace("</style>", top_rank_css() + "</style>", 1)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(html)


if __name__ == "__main__":
    from democratic_ratings import track_votes

    build_site(pc.load_runs(), track_votes())
    print(f"Wrote {SITE_OUTPUT}")
