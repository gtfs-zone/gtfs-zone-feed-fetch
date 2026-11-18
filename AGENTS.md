# AGENTS.md

Python library shared by feed-catalog, timetable-sites and crimes. See
[README.md](README.md) for the modules.

- **Pure where it can be**: no I/O outside `fetch` and `scan`; `store` only
  builds and parses keys and the index, the caller talks to the bucket.
- **Outputs are a contract**: sites' `content.json` and the catalog's
  `gtfs/<sha256>.facts.json` come from `feed_facts`. Bump `FACTS_VERSION`
  whenever the same zip would give a different document.
- **Memory**: `scan` keeps a count per stop and nothing per trip. Keep it that
  way; run it under `pool.run_all` with a cap.
- **Tests** run against no services: `respx` for HTTP, fixture zips built in
  `tests/conftest.py`.
- **Commits**: Conventional Commits, enforced by the `commit-msg` hook. Never
  add Co-Authored-By trailers. Release with `cz bump` on main.
- **Logging**: module loggers are named `log`, never `logger`.
