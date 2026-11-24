"""
THE PAGE BUILDER
================
Builds index.html, the leaderboard page, from the page design in site/template.html.

The page doesn't get finished numbers. It gets the raw runs (who, which track, faults, time), the track ratings and the scoring
settings, and works out every run's points, every Elo and every rank itself, inside the visitor's browser. That's why the page has
its own copy of the scoring (in site/template.html) that has to match points_calculator.py.

driver.py runs this automatically. It can also be run on its own ("python build_site.py") to rebuild just the page.
"""

import base64
import datetime
import gzip
import json

import polars as pl   # The table library

import points_calculator as pc


SITE_TEMPLATE = "site/template.html"   # The page design, with an empty slot (__DATA__) where the data goes
SITE_OUTPUT = "index.html"             # The finished page

# The colour of the very top Elo rank's badge (light mode, dark mode). It's added to the page separately so the colour is ready the
# moment someone reaches that rank, even though nobody holds it now
TOP_RANK_COLOURS = ("#b8002e", "#ff4d6d")


def top_rank_css():
    # Writes the top rank's badge colour as a style rule for the page, in both light and dark mode
    light, dark = TOP_RANK_COLOURS
    cls = ".r-" + pc.RANKS[-1][0].replace(" ", "-")
    return (
        f'{cls} {{ --rc: {light}; }}\n'
        f'@media (prefers-color-scheme: dark) {{ :root:not([data-theme="light"]) {cls} {{ --rc: {dark}; }} }}\n'
        f':root[data-theme="dark"] {cls} {{ --rc: {dark}; }}\n'
    )


def settings():
    # The scoring settings from points_calculator.py, handed to the page so its copy of the scoring uses exactly the same numbers
    return {
        "level_steps": pc.LEVEL_STEPS,
        "top_rating_spread": pc.TOP_RATING_SPREAD,
        "points_at_level_8": pc.POINTS_AT_LEVEL_8,
        "fault_cap": pc.FAULT_CAP,
        "fault_steepness": pc.FAULT_STEEPNESS,
        "zero_fault_bonus": pc.ZERO_FAULT_BONUS,
        "low_fault_share": pc.LOW_FAULT_SHARE,
        "low_fault_reach": pc.LOW_FAULT_REACH,
        "fault_median_prior_runs": pc.FAULT_MEDIAN_PRIOR_RUNS,
        "time_shift_max": pc.TIME_SHIFT_MAX,
        "run_decay": pc.RUN_DECAY,
        "min_runs": pc.MIN_RUNS,
        "reference_runs": pc.REFERENCE_RUNS,
        "max_counted_runs": pc.MAX_COUNTED_RUNS,
        "ranks": pc.RANKS,
        "rank_tiers": pc.RANK_TIERS,
        "points_ranks": pc.POINTS_RANKS,
        "elo_curve": pc.ELO_CURVE,
    }


def site_data(runs_df, votes_df):
    # Everything the page needs, and nothing more: today's date, the settings, the list of player names, the list of tracks
    # (name, level, rating, number of votes), and every run.
    # To keep the page small, each run is written as four numbers: [which player, which track, faults, time]. "Which player" is
    # a position in the player list (0 = the first name) instead of the full name, and the same for tracks. With about 69,000 runs,
    # writing every name out in full would make the page several times bigger
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
    assert runs.height == runs_df.height, "every run needs its player and track in the page data"   # Safety check: no run got lost
    return {
        "generated": datetime.date.today().isoformat(),   # Shown at the top of the page as "Updated ..."
        "settings": settings(),
        "players": players["Player"].to_list(),
        "tracks": tracks.to_dicts(),
        "runs": runs.rows(),
    }


def build_site(runs_df, votes_df, path=SITE_OUTPUT):
    # Packs the data and puts it into the page.
    # The data is compressed (gzip, like a zip file) and then turned into plain letters and numbers (base64) so it can sit inside the
    # page. The page unpacks it when it opens. That keeps the page small and means there's no readable table in the page's source.
    # It isn't secret, though: anyone who knows how can unpack it. So only put things in site_data that are fine to be public
    # (player names, tracks, faults and times). Account ids and track ids never go in
    data = json.dumps(site_data(runs_df, votes_df), ensure_ascii=False, separators=(",", ":"))
    packed = base64.b64encode(gzip.compress(data.encode("utf-8"), mtime=0)).decode("ascii")
    with open(SITE_TEMPLATE, encoding="utf-8") as f:
        html = f.read().replace("__DATA__", packed)
    html = html.replace("</style>", top_rank_css() + "</style>", 1)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(html)


# Everything below only happens when this file is run directly: rebuild just the page
if __name__ == "__main__":
    from rating_sheet import track_votes

    build_site(pc.load_runs(), track_votes())
    print(f"Wrote {SITE_OUTPUT}")
