"""
THE RATING SHEET
================
Downloads the community track rating sheet from Google Sheets and reads the votes off it.
On the sheet, each row is a track and each column is a rider; a cell holds that rider's difficulty vote for that track (like 8.4).
A track's rating is later taken as the median of its votes (see track_ratings in points_calculator.py).

Run this file on its own ("python rating_sheet.py") to print the rating every level 8 and 9 track is scored at.
The sheet must stay viewable by anyone with the link, or the download fails.
"""

import io
import sys
import urllib.request   # For downloading the sheet from the internet

import polars as pl     # The table library that reads the sheet


# CONSTANTS
# --------------------------------------------------------------------------------------------------------------------------------------------------------------------
# Which Google Sheet to read. The id is the long code in the sheet's web address; the "gid" picks the tab (0 = the first tab)
TRACK_RATINGS_SHEET_ID = "1gBv5KJDzXPCv_MgnghG8_GPwmJ309oVKJwmg9m2z2eg"
TRACK_RATINGS_GID = 0
SHEET_HEADER_ROW = 4               # The first 4 rows are instructions and notes; the column names are on row 5
SHEET_META_COLUMNS = ["Track", "Level", "Avg", "Med", "#"]   # The columns that aren't voters (the sheet's own average or median and vote count). Every other column is one rider's votes
VOTE_MAX_GAP = 1.5                 # A vote more than 1.5 away from the track's level must be a typo (85 meant as 8.5), so it's ignored


def fetch_sheet():
    # Downloads the sheet as a spreadsheet file and reads it in, treating every cell as text for now
    url = (
        f"https://docs.google.com/spreadsheets/d/{TRACK_RATINGS_SHEET_ID}"
        f"/export?format=csv&gid={TRACK_RATINGS_GID}"
    )
    with urllib.request.urlopen(url) as response:
        csv_bytes = response.read()
    sheet = pl.read_csv(io.BytesIO(csv_bytes), skip_rows=SHEET_HEADER_ROW, infer_schema=False)
    # The full tracks end at the first blank row. Below it the sheet has a separate section for the extra-checkpoint versions
    # ("CPs / 50CPS", with its own header row), which don't count
    blank = sheet["Track"].is_null().arg_true()
    return sheet.head(blank[0]) if len(blank) else sheet


def sheet_tracks(sheet):
    # Every track listed on the sheet, with its level, whether anyone has voted on it yet or not
    return sheet.select("Track", pl.col("Level").cast(pl.Int64))


def sheet_votes(sheet):
    # Turns the grid of votes into a simple list, one line per vote: which track, its level, who voted and what they gave it.
    # Empty cells are skipped. A cell that isn't a number, or is more than VOTE_MAX_GAP from the track's level, is skipped too,
    # and a warning is printed naming the vote, so it can be fixed on the sheet
    voters = [c for c in sheet.columns if c not in SHEET_META_COLUMNS]
    cells = (
        sheet.unpivot(index=["Track", "Level"], on=voters, variable_name="Voter", value_name="Cell")   # Grid -> one line per cell
        .with_columns(pl.col("Level").cast(pl.Int64), pl.col("Cell").str.strip_chars())
        .filter(pl.col("Cell").is_not_null() & (pl.col("Cell") != ""))                                # Drop empty cells
        .with_columns(pl.col("Cell").cast(pl.Float64, strict=False).alias("Vote"))                    # Read the text as a number
    )
    usable = pl.col("Vote").is_not_null() & ((pl.col("Vote") - pl.col("Level")).abs() <= VOTE_MAX_GAP)
    for row in cells.filter(~usable).iter_rows(named=True):
        print(
            f"Ignored vote {row['Cell']!r} by {row['Voter']} on {row['Track']} (level {row['Level']})",
            file=sys.stderr,
        )
    return cells.filter(usable).drop("Cell")


def track_votes(sheet=None):
    # One line per track on the sheet, holding all of its votes together (an empty list if nobody has voted).
    # This is what the scoring uses. If no sheet is given, it downloads one first
    if sheet is None:
        sheet = fetch_sheet()
    return (
        sheet_tracks(sheet)
        .join(sheet_votes(sheet).group_by("Track", "Level").agg(pl.col("Vote").alias("Votes")), on=["Track", "Level"], how="left")
        .with_columns(pl.col("Votes").fill_null(pl.lit([], dtype=pl.List(pl.Float64))))
    )


# Everything below only happens when this file is run directly: it prints the level 8 and 9 ratings as they're scored
if __name__ == "__main__":
    import points_calculator as pc   # Loaded here rather than at the top, because points_calculator itself loads this file

    pl.Config.set_tbl_rows(-1)       # Print every row, not a shortened table
    pl.Config.set_fmt_str_lengths(40)

    # Ratings as scored: the median vote, with any hand-set overrides applied
    ratings = pc.track_ratings(pc.load_runs(), track_votes())
    for level in (8, 9):
        print(f"\n===== LEVEL {level} =====")
        print(
            ratings.filter(pl.col("Level") == level)
            .select("Track", "VoteCount", pl.col("TrackRating").round(2))
            .sort("TrackRating", descending=True)
        )
