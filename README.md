# FLAC Cover Fixer

A Mac app that checks every album in a FLAC library (`Artist/Album/01 - Title.flac`)
and makes sure each album folder has artwork the **Eversolo T10** will display.

* Finds albums with missing, badly named, too small, too large, damaged or
  embedded-only artwork.
* Works out the album from FLAC tags (ALBUMARTIST, ALBUM, DATE, MusicBrainz IDs,
  barcode) and falls back to the folder names (`1997 - OK Computer [FLAC 24-96]`
  → *OK Computer*, 1997).
* Uses local art first (embedded pictures, oddly named images, oversized covers).
  Otherwise it searches **Deezer**, **MusicBrainz / Cover Art Archive**,
  **Discogs** and **Apple Music**.
* Shows a **review screen** where every proposal can be checked, changed, re-searched,
  replaced with your own file, or skipped. Nothing is written until you click *Apply*.
* Writes `cover.jpg` into the album folder. Old cover/folder/front images are
  backed up and *Tools ▸ Undo Last Apply* restores them.

## What the Eversolo needs

Eversolo's music-library guide says the cover image goes **in the album folder**,
named **`cover`, `folder` or `front`**, as **JPG or PNG** (any letter case), ideally
**500×500 or 800×800** pixels ([Eversolo streamers music library guide][ev-lib]).
If a folder holds only one picture the player uses it whatever its name; this
app still writes `cover.jpg` so the result is predictable. Eversolo hasn't
published a guide specific to the T10, so this assumes it uses the same
music-library software as the other streamers.

This app therefore writes:

| Setting | Value |
|---|---|
| File name | `cover.jpg` in each album folder |
| Size | 800×800 (no upscaling; smaller sources are kept at their size) |
| Format | baseline (non-progressive) sRGB JPEG, metadata stripped, ≤ 900 KB |
| Other `cover.*` / `folder.*` / `front.*` files | moved to the backup folder so the player can't pick a stale one |
| FLAC files | **never modified** |

On the T10, turn on **Priority local image** in the music library scan settings
([guide][ev-lib]; a [DMP-A6 owner][ev-forum] reports it sits next to *Matching mode*)
and rescan the library after applying.

## Install (Mac mini M4)

You need Homebrew Python 3.13 (PySide6 publishes wheels for it):

```bash
brew install python@3.13
```

Then build the app (runs the tests first):

```bash
git clone https://github.com/pythagora5/flac-lib-covers.git
```

```bash
cd flac-lib-covers
```

```bash
scripts/build_app.sh --install
```

That creates **/Applications/FLAC Cover Fixer.app**. The first time it opens a
folder under `/Volumes`, macOS asks for permission to access removable
volumes. Click *Allow*.

To run from source without building: `scripts/run.sh`.

## Using it

1. Check the library path (default `/Volumes/2TB`) and click **Scan Library**.
2. Albums whose artwork is already fine are counted and hidden. Albums with a
   problem appear straight away and fill in as lookups finish.
3. Review them:
   * **Ticked** rows are confident matches (score ≥ 85 %, adjustable).
   * *Show ▸ Needs review* lists the uncertain ones.
   * Click a row to see the current and proposed covers and all candidates.
     Click a candidate to use it.
   * Fix the artist/album text and click **Search Again (all sources)**, or
     **Use Image File…** to pick your own.
4. Click **Apply Ticked**.

**Settings** (⌘,) holds your **Discogs personal access token** (stored in the
macOS Keychain), output size, the "is it OK?" thresholds, and thread counts.

## Performance

Designed for a library of a few thousand albums on a USB drive:

* **Scan**: one directory read per folder. FLAC files are never opened during
  the scan, and only image *headers* are read. Top-level folders are scanned in
  parallel (4 threads by default; use 2 for a slow spinning disk, 8+ for an SSD).
  Results are cached in SQLite, keyed by folder and image modification times,
  so a re-scan only lists folders. A 2,000-album / 24,000-file test library
  scans in about 1 s on SSD.
* **Tags**: read only for albums that need fixing, from at most 3 tracks.
  Mutagen reads just the metadata blocks, not the audio.
* **Lookups** run 8 albums at a time, with a rate limiter per website.
  Sources are tried **in tiers** and searching stops at the first strong match:
  1. Deezer (fast, 1000×1000), plus MusicBrainz first if the tags hold a MusicBrainz ID
  2. MusicBrainz / Cover Art Archive and Discogs
  3. Apple Music (only about 20 requests/minute are allowed)
* Only small previews are downloaded for review. Full images are fetched when
  you apply. Lookups and previews are cached for 30 days.

## Where things are kept

| What | Where |
|---|---|
| Settings | `~/Library/Application Support/FLAC Cover Fixer/settings.json` |
| Backups + undo manifests | `~/Library/Application Support/FLAC Cover Fixer/Backups/<date-time>/` |
| Change log | `~/Library/Logs/FLAC Cover Fixer/changes.log` |
| Caches (safe to delete) | `~/Library/Caches/FLAC Cover Fixer/` |

## Development

```bash
scripts/setup.sh
```

```bash
.venv/bin/python -m pytest -q
```

Code layout: `flaccovers/scanner.py` (scan + checks), `metadata.py` (tags/folder
parsing), `sources/` (Deezer, MusicBrainz/CAA, Discogs, Apple Music), `matcher.py`
(scoring), `lookup.py` (local + online search), `applier.py` (writing, backup,
undo), `gui/` (PySide6 interface).

## References

* Eversolo streamers music library guide (cover naming, size, *Priority local image*): [zidoo.tv][ev-lib]
* StereoNET DMP-A6 owners thread (where *Priority local image* is): [stereonet.com][ev-forum]
* MusicBrainz API rate limits and User-Agent rules: <https://musicbrainz.org/doc/MusicBrainz_API/Rate_Limiting>
* Cover Art Archive API: <https://musicbrainz.org/doc/Cover_Art_Archive/API>
* Discogs API (authentication, 60 requests/min): <https://www.discogs.com/developers>
* iTunes Search API: <https://performance-partners.apple.com/search-api>
* Deezer API: <https://developers.deezer.com/api>

[ev-lib]: https://shop.zidoo.tv/a/support/music-streaming/eversolo-streamers-music-library-user-guide
[ev-forum]: https://www.stereonet.com/forums/topic/580277-eversolo-dmp-a6-owners-discussion-thread/page/20/
