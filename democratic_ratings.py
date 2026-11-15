
import io
import sys
import urllib.request

import polars as pl


# CONSTANTS

# Community track-difficulty opinion sheet (Track, Level, Avg, #, then one column per voter)
TRACK_RATINGS_SHEET_ID = "1gBv5KJDzXPCv_MgnghG8_GPwmJ309oVKJwmg9m2z2eg"
TRACK_RATINGS_GID = 0
SHEET_HEADER_ROW = 4               # First 4 rows are sheet instructions/notes; row 5 is the real header
SHEET_META_COLUMNS = ["Track", "Level", "Avg", "#"]
VOTE_MAX_GAP = 1.5                 # A vote further than this from the track's sheet level is a typo (85 for 8.5) and is ignored

# Voter offsets: each vote = track rating + voter offset + noise
CORRECT_VOTER_LEAN = False         # Off: scoring uses the plain median vote. Offsets are still printed as a check; turn on once voters are many and sparse enough for one lean to swing a track
OFFSET_PRIOR_VOTES = 5             # Offsets start as if backed by 5 phantom votes at 0, so new voters barely move
FIT_TOLERANCE = 1e-6               # Stop once no offset moves more than this between passes
FIT_MAX_PASSES = 500


def fetch_sheet():
    # Pulls the live Google Sheet export, everything as strings
    url = (
        f"https://docs.google.com/spreadsheets/d/{TRACK_RATINGS_SHEET_ID}"
        f"/export?format=csv&gid={TRACK_RATINGS_GID}"
    )
    with urllib.request.urlopen(url) as response:
        csv_bytes = response.read()
    return pl.read_csv(io.BytesIO(csv_bytes), skip_rows=SHEET_HEADER_ROW, infer_schema=False)


def sheet_tracks(sheet):
    # Every track listed on the sheet, voted or not
    return sheet.select("Track", pl.col("Level").cast(pl.Int64))


def sheet_votes(sheet):
    # One row per vote: Track, Level, Voter, Vote; blank and empty-header columns drop out.
    # Cells that aren't a number, or sit more than VOTE_MAX_GAP from the track's level, are ignored with a warning
    voters = [c for c in sheet.columns if c not in SHEET_META_COLUMNS]
    cells = (
        sheet.unpivot(index=["Track", "Level"], on=voters, variable_name="Voter", value_name="Cell")
        .with_columns(pl.col("Level").cast(pl.Int64), pl.col("Cell").str.strip_chars())
        .filter(pl.col("Cell").is_not_null() & (pl.col("Cell") != ""))
        .with_columns(pl.col("Cell").cast(pl.Float64, strict=False).alias("Vote"))
    )
    usable = pl.col("Vote").is_not_null() & ((pl.col("Vote") - pl.col("Level")).abs() <= VOTE_MAX_GAP)
    for row in cells.filter(~usable).iter_rows(named=True):
        print(
            f"Ignored vote {row['Cell']!r} by {row['Voter']} on {row['Track']} (level {row['Level']})",
            file=sys.stderr,
        )
    return cells.filter(usable).drop("Cell")


def voter_offsets(votes_df):
    # Alternates between track means of offset-corrected votes and each voter's shrunk mean gap to them.
    # Offsets only learn from tracks voters share, so passing easier tracks isn't mistaken for harsh voting.
    # They are centred so the vote-weighted average offset is 0: the crowd as a whole sets the scale.
    offsets = votes_df.select(pl.col("Voter").unique(), pl.lit(0.0).alias("Offset"))

    for _ in range(FIT_MAX_PASSES):
        with_offsets = votes_df.join(offsets, on="Voter")
        tracks = with_offsets.group_by("Track", "Level").agg((pl.col("Vote") - pl.col("Offset")).mean().alias("TrackMean"))

        new_offsets = (
            votes_df.join(tracks, on=["Track", "Level"])
            .group_by("Voter")
            .agg(
                pl.len().alias("VoteCount"),
                ((pl.col("Vote") - pl.col("TrackMean")).sum() / (pl.len() + OFFSET_PRIOR_VOTES)).alias("Offset"),
            )
            .with_columns(
                pl.col("Offset")
                - (pl.col("Offset") * pl.col("VoteCount")).sum() / pl.col("VoteCount").sum()
            )
        )

        change = (
            new_offsets.join(offsets, on="Voter", suffix="Old")
            .select((pl.col("Offset") - pl.col("OffsetOld")).abs().max())
            .item()
        )
        offsets = new_offsets.select("Voter", "Offset")
        if change < FIT_TOLERANCE:
            break

    return new_offsets.select("Voter", "VoteCount", "Offset").sort("Offset")


def track_votes(sheet=None):
    # One row per sheet track with its votes as a list (empty if nobody voted)
    if sheet is None:
        sheet = fetch_sheet()

    votes = sheet_votes(sheet)
    if CORRECT_VOTER_LEAN:
        # Offset-corrected, clamped to the track's raw vote range: the correction can move a rating
        # within what voters said, never outside it (four 9.0 votes can't make a track 8.98)
        votes = votes.join(voter_offsets(votes), on="Voter").with_columns(
            (pl.col("Vote") - pl.col("Offset"))
            .clip(pl.col("Vote").min().over("Track", "Level"), pl.col("Vote").max().over("Track", "Level"))
        )

    return (
        sheet_tracks(sheet)
        .join(votes.group_by("Track", "Level").agg(pl.col("Vote").alias("Votes")), on=["Track", "Level"], how="left")
        .with_columns(pl.col("Votes").fill_null(pl.lit([], dtype=pl.List(pl.Float64))))
    )

if __name__ == "__main__":
    import points_calculator as pc   # Imported here; points_calculator imports this module at the top

    pl.Config.set_tbl_rows(-1)
    pl.Config.set_fmt_str_lengths(40)

    sheet = fetch_sheet()
    print("Voter leans" + ("" if CORRECT_VOTER_LEAN else " (check only, not applied)"))
    print(voter_offsets(sheet_votes(sheet)))

    # Final ratings as scored: median vote, overrides applied
    ratings = pc.track_ratings(pc.load_runs(), track_votes(sheet))
    for level in (8, 9):
        print(f"\n===== LEVEL {level} =====")
        print(
            ratings.filter(pl.col("Level") == level)
            .select("Track", "VoteCount", pl.col("TrackRating").round(2))
            .sort("TrackRating", descending=True)
        )
