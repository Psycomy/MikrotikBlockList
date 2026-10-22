# IP Lookup Page Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A public, spectacular "is this IP listed?" page on GitHub Pages, fed by a new daily
`lookup.json` (entries, sources, variants, countries). Also, NOTICE.md gains the Spamhaus
copyright it currently lacks.

**Architecture:**
- The daily build (`python -m mbl build`) gains an optional, failure-isolated step that writes
  `lookup.json` to the `lists` branch.
  - Countries come from the DB-IP Country Lite CSV, cached monthly in Actions.
- A static site in `site/` (vanilla JS ES modules, vendored d3-geo/topojson) reads `lookup.json`
  from raw.githubusercontent.com and searches entirely in the browser.
- A `pages` workflow deploys `site/`.

**Tech Stack:**
- Python 3.12, standard library only (generator);
- HTML/CSS/vanilla JS ES modules, plus vendored d3-array 3.2.4, d3-geo 3.1.1, topojson-client
  3.1.0 and world-atlas 2.0.2 `land-110m.json`;
- `node --test` (Node built into ubuntu-latest) for the JS logic;
- GitHub Actions: `actions/cache`, `actions/upload-pages-artifact`, `actions/deploy-pages`.

**Spec:** `docs/superpowers/specs/2026-10-22-lookup-page-design.md`. The visual reference is
`docs/superpowers/specs/assets/2026-10-22-lookup-prototype.html`. Read both.

## Global Constraints

- **Python:** generator code is standard library only, Python 3.12, and matches the existing
  `mbl/` style (type hints, small functions, `unittest`).
- **No npm or build tools:** third-party JS lives vendored in `site/vendor/` at the exact versions
  above. The page makes no requests except to its own origin and
  `https://raw.githubusercontent.com/Psycomy/MikroBlockList/lists/`.
- **No backend or analytics.** The searched IP never leaves the browser.
- **Always dark:** no light theme. `prefers-reduced-motion: reduce` means a static map, no comets,
  no waves, and results shown directly.
- **Spamhaus name:** only as data attribution (result card, source table, ticker entry), never in
  headings, tagline, ticker label or promotional wording.
- **DB-IP attribution** shown on the page: "IP Geolocation by DB-IP" linking to https://db-ip.com
  (CC BY 4.0), with the DB-IP month used.
- **Size:** `lookup.json` at most 3 MB gzip for 40k IPv4 entries.
- **Isolation:** a `lookup.json` failure never fails the build or withholds any list (warning
  only, like IPv6).
- **Ticker wording:** "on the list right now" / "en la lista ahora". Never "live attacks".
- **States:** listed = red "BLOCKED"; partial CIDR overlap = amber "PARTIALLY LISTED"; not
  listed = green; unknown (IPv6 withheld, data unavailable, data older than 2 days) = amber,
  never green.
- **Languages:** ES/EN from `navigator.language` (es* → ES, else EN), with a toggle remembered in
  `localStorage`, wrapped in try/catch.
- **Repo name** in all URLs: `Psycomy/MikroBlockList`. Page URL:
  `https://psycomy.github.io/MikroBlockList/`.

## Review Focus

1. **IPv4-mapped IPv6** (`::ffff:185.220.101.4`) should be treated as the IPv4 address. Test in
   Task 5.
2. **Non-canonical input:**
   - surrounding spaces, uppercase/compressed IPv6 (`2001:DB8::1`), and a host-bit CIDR
     (`185.220.101.4/22`) must work, the CIDR normalized to its network;
   - leading-zero octets (`010.1.1.1`) must be rejected as invalid, like the Python parser does.

   Test in Task 5.
3. **IPv6 query on a withheld day** (`v6: null` in `lookup.json`) must be amber "IPv6 list not
   published today", never green. Tests in Tasks 3 and 5.
4. **A source that errored today** must not appear as a source of any entry, even though its
   previous data was in yesterday's list. Test in Task 3.
5. **A `?ip=` value that is invalid or malicious** (`?ip=<script>`) must show an invalid-input
   message with no HTML injection: the UI only uses `textContent`. Tests in Tasks 5 and 7.

---

### Task 1: Keep source copyright notices (Spamhaus) and show them in NOTICE.md

**Files:**
- Modify: `mbl/parsers.py` (`ParseResult`, `_parse_plain`, `_parse_jsonl_cidr`)
- Modify: `mbl/fetch.py` (`SourceResult`, `_fetch_one`)
- Modify: `mbl/render.py` (`_notice`)
- Test: `tests/test_parsers.py`, `tests/test_render.py`, `tests/test_fetch.py`

**Interfaces:**
- Produces:
  - `ParseResult.notice: str = ""` and `SourceResult.notice: str = ""`, a one-line copyright plus
    date string from the source file, or "".
  - `render.source_notice(result: SourceResult, fetched_at: str) -> str`: the notice to show, with
    the Spamhaus fallback. Task 3 reuses it.

- [ ] **Step 1: Write failing tests**
  - `test_plain_keeps_copyright_notice`: `parse("plain", "; Spamhaus DROP List 2026/10/22 - (c) 2026 The Spamhaus Project SLU\n; https://x\n; Last-Modified: Wed, 21 Oct 2026 14:04:29 GMT\n1.10.16.0/20 ; SBL1\n").notice == "Spamhaus DROP List 2026/10/22 - (c) 2026 The Spamhaus Project SLU; Last-Modified: Wed, 21 Oct 2026 14:04:29 GMT"`.
  - `test_jsonl_keeps_metadata_notice`: a line `{"type":"metadata","timestamp":1792673042,"copyright":"(c) 2026 The Spamhaus Project SLU"}` gives `notice == "(c) 2026 The Spamhaus Project SLU; timestamp 2026-10-21T12:44:02Z"`.
  - `test_plain_without_copyright_has_empty_notice`: `parse("plain", "1.1.1.1\n").notice == ""`.
  - `test_fetch_one_carries_notice` (`tests/test_fetch.py`, using its existing fake-download
    pattern): `SourceResult.notice` equals the parser's.
  - `test_notice_md_shows_source_notices` (`tests/test_render.py`): NOTICE.md contains the
    Spamhaus line for a result with a notice. For a source named `spamhaus-*` with an empty
    notice, it contains `(c) The Spamhaus Project SLU (fetched <stamp>)`.
- [ ] **Step 2: Run** `python3 -m unittest tests.test_parsers tests.test_fetch tests.test_render`. Expected: the new tests FAIL.
- [ ] **Step 3: Implement.**
  - **Plain parser:** the first comment line (`;` or `#`) containing `(c)`, stripped of the
    leading `;`/`#` and spaces. If a `Last-Modified:` comment line exists, append `; ` and that
    line, stripped the same way.
  - **jsonl parser:** from a record with `"copyright"`: the copyright, plus `; timestamp
    <UTC ISO>` when an integer `timestamp` is present.
  - **NOTICE.md:** add a "Notice" column to the source table, filled with
    `source_notice(r, stamp)`. The fallback applies only when `r.source.name` starts with
    `spamhaus` and the notice is empty.
- [ ] **Step 4: Run** `python3 -m unittest discover`. Expected: all OK.
- [ ] **Step 5: Commit** `feat: keep source copyright notices (Spamhaus) in NOTICE.md`.

### Task 2: DB-IP country database

**Files:**
- Create: `mbl/geo.py`
- Modify: `mbl/__main__.py` (new `dbip-fetch` subcommand)
- Test: `tests/test_geo.py`, with fixture `tests/fixtures/dbip_sample.csv.gz` (a few dozen lines:
  IPv4 and IPv6, including a CIDR-sized range split across two countries)

**Interfaces:**
- Produces:
  - `class CountryDb` with `CountryDb.load(path: Path) -> CountryDb` (gzip CSV `start,end,CC`)
    and `country(first: int, last: int, version: int) -> str`.
    - `country` returns the code when one DB-IP row covers the whole `[first, last]`.
    - It returns `""` when the range spans more than one country or is not covered, and for `ZZ`.
    - It uses sorted start arrays and `bisect`; there is one array per version.
  - `CountryDb.month: str`: `YYYY-MM`, taken from the file name `dbip-country-lite-YYYY-MM.csv.gz`.
  - `fetch_dbip(cache_dir: Path, today: date, fetcher=None) -> Path | None`:
    - returns the cached file for `today`'s month if present;
    - otherwise downloads `https://download.db-ip.com/free/dbip-country-lite-{YYYY-MM}.csv.gz`
      into `cache_dir`;
    - on failure (HTTP error, or a body that is not gzip), tries the previous month the same way;
    - returns `None` if both fail;
    - removes cached files of other months after a successful fetch.
  - CLI: `python -m mbl dbip-fetch --cache DIR` prints the path, exits 0; or prints a warning and
    exits 0 with no file. It never fails the workflow.

- [ ] **Step 1: Write failing tests**
  - `test_country_single_row`: a /24 inside an `AU` row gives `"AU"`.
  - `test_country_spanning_two_rows_is_empty`;
  - `test_country_uncovered_and_zz_empty`;
  - `test_ipv6_lookup`;
  - `test_month_from_filename`;
  - `test_fetch_uses_cache` (no fetcher call when `dbip-country-lite-2026-10.csv.gz` exists in
    the cache dir);
  - `test_fetch_falls_back_to_previous_month` (the fetcher raises `HTTPError 404` for 2026-10 and
    serves gzip bytes for 2026-09: the result is named `...2026-09.csv.gz`);
  - `test_fetch_rejects_non_gzip` (an HTML body gives `None` and leaves no file);
  - `test_fetch_both_missing_returns_none`;
  - `test_cli_dbip_fetch_never_fails` (exit code 0 when the fetcher fails).
- [ ] **Step 2: Run** `python3 -m unittest tests.test_geo`. Expected: FAIL (no module).
- [ ] **Step 3: Implement** `mbl/geo.py`. Download with the same `User-Agent` as `mbl.fetch`. The
  default fetcher returns bytes.
- [ ] **Step 4: Run** `python3 -m unittest discover`. Expected: all OK.
- [ ] **Step 5: Commit** `feat: DB-IP country lookup with monthly cache`.

### Task 3: `lookup.json` generation, wired into the build

**Files:**
- Create: `mbl/lookup.py`
- Modify: `mbl/build.py` (`build()` gains `dbip_path: Path | None = None`, plus an optional step
  at the end), `mbl/__main__.py` (`build --dbip PATH`, optional)
- Test: `tests/test_lookup.py`, plus one test in `tests/test_build.py`

**Interfaces:**
- Consumes: `CountryDb` (Task 2) and `render.source_notice` (Task 1).
- Produces:
  - `lookup_data(variants: dict[str, list[IPv4Network]], variants6: dict[str, list[IPv6Network]] | None, results: list[SourceResult], generated_at: datetime, geo: CountryDb | None) -> dict`
  - `write_lookup(out_dir: Path, data: dict) -> None` writes `lookup.json`, compact (no spaces).
  - JSON format (version 1, read by Task 5):

```json
{"format": 1, "generated_at": "2026-10-22T04:17:00Z", "ipv6_published": true,
 "dbip_month": "2026-10",
 "sources": [{"name": "spamhaus-drop", "category": "attack", "url": "https://...",
              "license_note": "...", "notice": "...", "entries": 1688, "entries6": 0, "ok": true}],
 "v4": {"full": [["185.220.100.0/22", [0, 4], "DE"], ...], "lite": ["185.220.100.0/22", ...]},
 "v6": {"full": [["2a0e:1234::/32", [1], ""]], "lite": [...]} }
```

  - `v6` is `null` when `variants6` is `None` (withheld), and `ipv6_published` is then false.
  - `dbip_month` is `null` without `geo`; every `cc` is then `""`.
  - Source indexes point into `sources`, which lists every result in catalog order.
  - `ok` is false when `r.error` is set. Such a source is never an index of any entry.
- In `build()`, after the existing `write_outputs(...)` call:

```python
    try:
        geo = CountryDb.load(dbip_path) if dbip_path else None
        write_lookup(Path(out_dir), lookup_data(variants, variants6, results, now, geo))
    except Exception as exc:
        print(f"warning: lookup.json not published ({type(exc).__name__}: {exc})", file=sys.stderr)
```

- [ ] **Step 1: Write failing tests** (`tests/test_lookup.py`, with `SourceResult`/`Source` built
  inline as in `tests/test_render.py`):
  - `test_membership_on_collapsed_entry`: sources A (`1.2.3.0/25`) and B (`1.2.3.128/25`)
    collapse to `1.2.3.0/24`, whose entry lists `[A, B]`.
  - `test_membership_partial_overlap_after_allowlist`: the published entry is a sub-range of a
    source's network, and that source is listed.
  - `test_errored_source_never_member`: a result with `error="boom"` and stale `networks`
    overlapping an entry is not in its index list, and has `ok: false`.
  - `test_lite_is_separate_list`: lite entries are written exactly as `variants["lite"]` CIDRs.
  - `test_ipv6_withheld`: `variants6=None` gives `v6 is None` and `ipv6_published is False`.
  - `test_countries_and_month`: with a fake `CountryDb`, entries get its codes and `dbip_month`.
    Without one, `cc == ""` and `dbip_month is None`.
  - `test_size_budget`: 40,000 synthetic `/32`s from 3 sources, each with 2 source indexes and a
    country, give `len(gzip.compress(json_bytes)) <= 3 * 1024 * 1024`.
  - `test_build_failure_isolated` (`tests/test_build.py`): patch `mbl.build.lookup_data` to raise.
    The build returns 0, the lists are written, `lookup.json` is absent, and stderr has
    `lookup.json not published`.
  - `test_build_writes_lookup` (`tests/test_build.py`): the normal build writes `lookup.json`
    with `format == 1`. Add `lookup.json` to the expected `FILES` set.
- [ ] **Step 2: Run** `python3 -m unittest tests.test_lookup tests.test_build`. Expected: FAIL.
- [ ] **Step 3: Implement** `mbl/lookup.py`.
  - **Membership:** per source, keep sorted `(first, last)` int intervals of its networks for the
    entry's version. For each entry, bisect to the intervals that could overlap.
  - **Country:** `geo.country(int(net.network_address), int(net.broadcast_address), version)`.
- [ ] **Step 4: Run** `python3 -m unittest discover`. Expected: all OK. Also run the real build
  locally:
  - `python3 -m mbl dbip-fetch --cache /tmp/dbip`
  - `python3 -m mbl build --out /tmp/mbl-out --dbip <printed path>`

  Then check `ls -l /tmp/mbl-out/lookup.json` and `gzip -c /tmp/mbl-out/lookup.json | wc -c`
  (must be ≤ 3145728).
- [ ] **Step 5: Commit** `feat: publish lookup.json for the lookup page`.

### Task 4: Workflow: DB-IP cache, lookup in publish, issue form sources

**Files:**
- Modify: `.github/workflows/build.yml`
- Modify: `.github/ISSUE_TEMPLATE/false_positive.yml` (add `c2intel`, and every other enabled
  source missing from the `source` dropdown)
- Test: `tests/test_issue_templates.py`

**Interfaces:**
- Consumes: the `python -m mbl dbip-fetch` CLI (Task 2) and `build --dbip` (Task 3).

- [ ] **Step 1: Write failing test** `test_false_positive_form_lists_every_source`. Read the form
  YAML as text (stdlib only: find the lines under the `id: source` block's `options:`). Assert
  that every `name` of an enabled `[[source]]` in `sources.toml` is among the options, plus
  `unknown`.
- [ ] **Step 2: Run** it. Expected: FAIL (`c2intel` is missing).
- [ ] **Step 3: Fix the form,** then edit the `publish` job in `build.yml`, before "Build":
  - `actions/cache@v4` with `path: .dbip` and `key: dbip-${{ steps.month.outputs.month }}`,
    preceded by a step `id: month` that writes `month=$(date -u +%Y-%m)` to `GITHUB_OUTPUT`;
  - a step `run: echo "DBIP=$(python -m mbl dbip-fetch --cache .dbip)" >> "$GITHUB_ENV"`;
  - in Build, add `${DBIP:+--dbip "$DBIP"}` to the `python -m mbl build` command.
- [ ] **Step 4: Run** `python3 -m unittest discover` and `python3 -c "import yaml,sys;yaml.safe_load(open('.github/workflows/build.yml'))"`. Expected: OK.
- [ ] **Step 5: Commit** `ci: DB-IP monthly cache and lookup.json in the publish job`.

### Task 5: Lookup core (pure JS) with Node tests

**Files:**
- Create: `site/js/core.js` (ES module, no DOM)
- Create: `site/js/core.test.mjs` (`node:test`, `node:assert/strict`)
- Modify: `.github/workflows/build.yml` `test` job: add step `run: node --test site/js/`

**Interfaces:**
- Consumes: the `lookup.json` format from Task 3.
- Produces (all exported from `site/js/core.js`):
  - `parseQuery(text: string) -> {version: 4|6, start: bigint, end: bigint, text: string, cidr: boolean} | null`
    - trims input;
    - turns `::ffff:a.b.c.d` into IPv4;
    - rejects leading-zero octets and prefixes out of range;
    - normalizes a host-bit CIDR to its network (`text` is the canonical form).
  - `buildIndex(data: object) -> Index`: sorted `bigint` start/end arrays for `v4.full`,
    `v4.lite`, `v6.full`, `v6.lite`, keeping the entry tuples. `Index` also has `sources`,
    `generatedAt` (`Date`), `ipv6Published`, `dbipMonth`, `counts {v4, v6}` and
    `sourcesWithData` (the count of `ok && entries+entries6 > 0`).
  - `search(index, query, now: Date) -> Result`, where `Result` is
    `{state: 'blocked'|'partial'|'clear'|'v6-unpublished', stale: boolean, entries: [{cidr, sources:[{name,category,url}], cc}], more: number, inFull: boolean, inLite: boolean, family: 'IPv4'|'IPv6'}`
    - `blocked`: one full or lite entry contains the whole query;
    - `partial`: entries overlap but none contains it. `entries` holds the first 20 and `more`
      the rest;
    - `stale`: data older than 2 days.
  - `reportUrl(query, result) -> string`:
    `https://github.com/Psycomy/MikroBlockList/issues/new?template=false_positive.yml&address=…&family=IPv4|IPv6&variant=full|lite&source=<first source name or unknown>`,
    URL-encoded.
  - `formatCount(n: number, lang: 'es'|'en') -> string` (`39.480` in es, `39,480` in en).

- [ ] **Step 1: Write failing tests** in `site/js/core.test.mjs`, against a small inline
  `lookup.json` object:
  - parse cases: valid v4, v6 compressed/uppercase, `::ffff:` mapped, host-bit CIDR normalized,
    `010.1.1.1` → null, `1.2.3.4/33` → null, `<script>` → null, `"  1.2.3.4  "` trimmed;
  - search: IP inside a full entry → blocked with its sources and `cc`; IP only in lite →
    blocked, `inFull` false and `inLite` true; IP outside → clear;
  - CIDR states: wider CIDR containing two entries → partial with 2 entries; a CIDR inside an
    entry → blocked; 25 overlapping entries → 20 entries plus `more: 5`;
  - IPv6 query with `v6: null` → `v6-unpublished`;
  - `stale` true when `now - generatedAt > 2 days`;
  - `reportUrl` contains `address=185.220.101.4`, `family=IPv4`, `variant=full`,
    `source=spamhaus-drop`; a lite-only result → `variant=lite`; no sources → `source=unknown`;
  - `formatCount(39480,'es') === '39.480'`.
- [ ] **Step 2: Run** `node --test site/js/`. Expected: FAIL (module missing).
- [ ] **Step 3: Implement** `site/js/core.js`: binary search over the start arrays, then scan
  neighbours for overlaps.
- [ ] **Step 4: Run** `node --test site/js/` and `python3 -m unittest discover`. Expected: all pass.
- [ ] **Step 5: Commit** `feat(site): lookup core with node tests`.

### Task 6: Page shell, background map, data loading, i18n

**Files:**
- Create:
  - `site/index.html`, `site/css/style.css`
  - `site/js/map.js`: the world dot map, comets, ripples, scan waves, reduced-motion and mobile
    handling
  - `site/js/i18n.js`: the string table, ES and EN
  - `site/js/app.js`: wiring, loading `lookup.json`, footer, ticker
  - `site/data/land-110m.json` (from world-atlas 2.0.2)
  - `site/data/centroids.json`: ISO alpha-2 → `[lon, lat]`; any public-domain or CC-BY dataset,
    credited in `site/data/README.md`
  - `site/vendor/` with d3-array 3.2.4, d3-geo 3.1.1 and topojson-client 3.1.0 `.min.js`, plus
    their LICENSE files
  - `site/favicon.svg`

**Interfaces:**
- Consumes: `buildIndex` and `formatCount` (Task 5).
- Produces, used by Task 7:
  - `map.js` exports `createMap(canvas) -> {comet(fromLonLat|null, big:boolean), wave(x, y, rgb), project(lon, lat) -> [x, y], reduced: boolean}`;
  - `i18n.js` exports `t(key, vars?)`, `setLang('es'|'en')` and `lang()`;
  - `app.js` holds the `index`, a promise that resolves when data is ready, and the `#q`, `#st`,
    `#bar` and `#r` elements.

- [ ] **Step 1: Build the landing page to match the prototype:**
  - title (`Mikro` `Block` `List`), tagline, search box with the SVG magnifier, help line with two
    example IPs, the privacy line;
  - footer: counts and update time from `lookup.json`, sources with data, DB-IP attribution with
    month, a home/non-commercial note, links to the repo and README;
  - ES/EN toggle;
  - ticker: 1 entry per ~1.5 s, sampled from `index` (`▲ 45.141.x.x · <flag> <country> · <source> · <category>`).
    Hidden below 700 px width and with reduced motion.
- [ ] **Step 2: Wire the map behaviour:**
  - comets spawn from the animation loop, at most 40 (16 on screens under 700 px);
  - the dot spacing is wider under 700 px (about half the dots);
  - fetch and `buildIndex` must not block the first frames: the map paints before the data
    arrives, and index building is chunked or runs in a Web Worker;
  - status line states: "loading list…" until data arrives; on fetch failure, amber "list
    unavailable" with a Retry button;
  - all dynamic text through `textContent`.
- [ ] **Step 3: Manual check:** run `python3 -m http.server -d site 8000`, open
  `http://localhost:8000/` (data loads from the real `lists` branch). Check:
  - desktop and 375 px widths;
  - DevTools "Emulate prefers-reduced-motion";
  - a hidden tab for 1 min and back: no pile-up;
  - ES/EN toggle;
  - DevTools offline: unavailable state, then Retry.

  The console must have no errors.
- [ ] **Step 4: Run** `node --test site/js/` and `python3 -m unittest discover`. Expected: pass.
- [ ] **Step 5: Commit** `feat(site): landing page with threat map, ticker and i18n`.

### Task 7: Search flow, effects and result cards

**Files:**
- Create: `site/js/search.js`
- Modify: `site/js/app.js`, `site/css/style.css`, `site/js/i18n.js`

**Interfaces:**
- Consumes: `parseQuery`, `search`, `reportUrl` (Task 5); `createMap`, `t`, the app elements
  (Task 6).
- Produces: `runSearch(text: string)`, called on submit, on example clicks and on load with
  `?ip=`.

- [ ] **Step 1: Implement the flow from the spec:**
  - **Invalid input:** inline error, no animation.
  - **Scan (~1 s):** rotating ring, button pulse, wave, progress bar, counter
    `> scanning N / total entries · S sources`.
  - **Blocked:**
    - red wave, then a big comet from `centroids[cc]` (random point when `cc` is empty) to the
      search box;
    - a short flash, then the red card: IP, flag and country (or "several countries"), the
      containing CIDR, `full`/`lite` pills, the family label, sources as links with category
      badges, Copy IP, and "Report a false positive" with `reportUrl`.
  - **Partial:** amber card listing the entries (+ "and N more").
  - **Clear:** green wave and card.
  - **`v6-unpublished` and stale:** amber.
  - **URL:** `history.replaceState` to `?ip=<canonical>`.
  - **Reduced motion:** skip the animations.
  - **Accessibility:** results go in `aria-live="polite"`.
  - **Sources:** a "Sources" link opens a table with each source's name, link, category,
    license_note and notice (Spamhaus copyright).
- [ ] **Step 2: Manual check** (same server as Task 6):
  - `185.220.101.4` (or any IP in today's list) → blocked;
  - `8.8.8.8` → clear;
  - a /16 around a listed /24 → partial;
  - an IPv6 address from `v6.full` → blocked;
  - `?ip=%3Cscript%3E` → invalid message, no injection;
  - reload with `?ip=` → auto-search;
  - the report link opens the pre-filled form;
  - copy works.

  The console must have no errors.
- [ ] **Step 3: Run** `node --test site/js/` and `python3 -m unittest discover`. Expected: pass.
- [ ] **Step 4: Commit** `feat(site): search flow, effects and result cards`.

### Task 8: Pages deploy, links and docs

**Files:**
- Create: `.github/workflows/pages.yml`
- Modify:
  - `README.md` (EN and ES: a link/badge near the top, a sentence in "Allowlist"/false positives);
  - `.github/ISSUE_TEMPLATE/false_positive.yml` (the address description: "check it first at
    https://psycomy.github.io/MikroBlockList/");
  - `docs/maintenance.md` (lookup.json warning line and DB-IP);
  - `CHANGELOG.md` (`[Unreleased]`: lookup page, lookup.json, Spamhaus notice, c2intel in the
    form).

- [ ] **Step 1: `pages.yml`:**
  - triggers: `push` to `main` with `paths: ["site/**", ".github/workflows/pages.yml"]`, plus
    `workflow_dispatch`;
  - permissions `contents: read`, `pages: write`, `id-token: write`;
  - `concurrency: pages`;
  - one job with `environment: github-pages` and steps: checkout (`persist-credentials: false`),
    `actions/configure-pages@v5`, `actions/upload-pages-artifact@v3` with `path: site`, and
    `actions/deploy-pages@v4`.
- [ ] **Step 2: Docs and links** as listed above. Keep the README tone and terseness.
- [ ] **Step 3: Run** `python3 -m unittest discover`, `node --test site/js/`, and a YAML parse of
  `pages.yml`. Expected: all pass.
- [ ] **Step 4: Commit** `ci: deploy the lookup page to GitHub Pages; docs and links`.

**After merge (controller, not the implementer):** enable Pages with source "GitHub Actions"
(`gh api -X POST repos/Psycomy/MikroBlockList/pages -f build_type=workflow`), dispatch
`pages.yml` and the `build` workflow, then check the live page.
