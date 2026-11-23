# gtfs-zone-feed-fetch

Shared Python library for the gtfs.zone pipelines (feed-catalog,
timetable-sites, crimes): one fetch per schedule and the facts every consumer
reads from it.

- `fetch`: a conditional GET streamed to a temp file, hashed on the way.
- `sniff`: what a body is from its first bytes.
- `store`: the schedule bucket's layout (`gtfs/<sha256>.zip`,
  `gtfs/<sha256>.facts.json`, `gtfs/index.json`) and `lookup` of a URL in
  the index.
- `urls`: `normalize_url`, the key the index is keyed by.
- `zipfacts`: what a zip's central directory says.
- `facts`: feed_info, service range, agencies, counts, languages, location and
  place tags of a zip, in one streaming pass (`scan`) or from a parsed feed
  (`Summary`).
- `localities`: the Overture localities containing each station, from a file
  written by `build` (the `localities` extra, or `scripts/localities.py`),
  for the municipality place tags.
- `pool`: run a function over many items in memory-capped worker processes.

```toml
[tool.uv.sources]
gtfs-zone-feed-fetch = { git = "https://github.com/gtfs-zone/gtfs-zone-feed-fetch.git", tag = "v0.1.0" }
```

```bash
scripts/check.sh   # lint, format, dependencies and tests
```

Licensed under AGPL-3.0-or-later.
