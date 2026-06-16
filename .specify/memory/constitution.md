# Setlist Builder Plugin Constitution

The Setlist Builder plugin (id: `setlist`) lets users create ordered
playlists of songs, optionally pinned to a specific arrangement per
slot, and play them sequentially with auto-advance.

## Core Principles

### I. Setlist as Ordered Sequence
A setlist is `(name, songs[])` where `songs` is ordered by `position`
1..N. Reordering re-numbers densely (`routes.py:147-152`). Insertion
appends at `MAX(position) + 1`. There are no gaps and no zero-based
indices on the wire.

### II. CRUD via REST, Playback via DOM
All persistence is REST. Playback uses the host's `playSong`
function and the `<audio>` element's `ended` event for auto-advance
(`screen.js:243-249`). The plugin never opens its own audio.

### III. Library is the Song Source of Truth
Songs are searched via the host's `/api/library?q=...` endpoint
(`screen.js:137`). The setlist stores `(filename, title, artist,
arrangement)` denormalized for display, but `filename` remains the
foreign key — if a song is removed from the library, the setlist
still references the filename and `playSong` will fail at click time.
[NEEDS CLARIFICATION: do we surface broken refs in the UI?]

### IV. Cascade Delete on Setlist Removal
Deleting a setlist removes both its `setlists` row and all
`setlist_songs` rows (`routes.py:74-80`). FK declared with
`ON DELETE CASCADE` but enforced explicitly to be DB-pragma-agnostic.

### V. Idempotent Frontend Hooks
A single `__slopsmithSetlistHooksInstalled` guard
(`screen.js:260-262`) prevents duplicate `showScreen` wrappers on
re-evaluation. The `audio.ended` listener is registered once per
script load on the existing element (`screen.js:241-250`).

### VI. Floating Progress Widget
The play-all flow renders a fixed-position progress overlay
(`screen.js:196-215`) with prev/next/stop. It is created on demand
and removed when the queue ends or the user stops.

## Inheritance from Slopsmith Core

Uses `context["config_dir"]` and `context["meta_db"]` (passed but not
currently used by routes). Frontend uses `playSong(filename)`,
`showScreen(id)`, the global `<audio>` element, and the library
search endpoint `/api/library`.

## Governance

Schema additions to `setlists` or `setlist_songs` bump
`plugin.json:version`. The wire shape of `GET /list`, `GET /{id}`,
and `POST /{id}/reorder` is part of the public contract for any
frontends or scripts driving the API.

**Version**: 1.0.0 | **Ratified**: 2026-05-09 | **Last Amended**: 2026-05-09
