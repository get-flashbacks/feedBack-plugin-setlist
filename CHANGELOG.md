# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed

- Made SQLite connection initialization race-safe so concurrent first requests share a single initialized connection.
- Return HTTP 400 for empty or non-string setlist names instead of a successful response or server error.
- Enabled `PRAGMA foreign_keys`, so the declared `ON DELETE CASCADE` is actually enforced. It defaulted to OFF per connection and was previously documentation only.
- Added `PRAGMA busy_timeout` so a concurrent writer no longer surfaces as "database is locked".
- Reject adding a song to a nonexistent setlist with 404. The insert previously succeeded and left a permanently orphaned row while still reporting success.
- Reject non-string `filename`/`title`/`artist`/`arrangement` on add with 400 instead of an opaque 500 from `sqlite3.InterfaceError`.
- Validate `song_ids` on reorder: non-list payloads no longer raise `TypeError`, duplicates and ids from another setlist are rejected instead of silently returning success.
- Keep positions dense (1..N) when reorder receives a partial id list. Positions were assigned `1..len(song_ids)`, producing duplicates and ambiguous ordering.
- Preserve the current relative order of songs omitted from a partial reorder. Omitted songs were appended in rowid order, so hoisting one song silently rewrote the rest of the setlist back to insertion order.
- Return 404 (not 200 with an `error` key) for missing setlists and missing songs, and 400 for `No filename` / `No song IDs`, so error paths are consistently non-2xx.
- Store `created_at`/`updated_at` with millisecond precision. Second-level truncation made "most recently updated first" ordering arbitrary for same-second writes; list ordering now also tie-breaks on id.
- `setup()` now resets the cached connection so a second mount no longer serves the previous database path.
- Frontend no longer throws when opening a deleted setlist; `slLoadDetail` checks for an error body before reading `data.songs`.

### Changed

- Renaming a setlist refreshes `updated_at`, so it moves to the top of the list like other mutations.
- Deleting a song that does not exist no longer re-numbers positions or touches the setlist's `updated_at`.

## [1.0.3] - 2026-09-08

### Changed

- Established the changelog at the plugin's current version.
