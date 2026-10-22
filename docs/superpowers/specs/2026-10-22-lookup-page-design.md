# "Is this IP listed?" lookup page

## Intent

A public page where anyone can type an IP and see at once whether MikroBlockList blocks it, in
which variants, and which public sources list it. It is useful for false-positive checks: the
issue form links to it, and a result links back to the form. It is also the project's shop
window, so it must be **visually spectacular**: a dark "cyber threat map" look with lots of
motion. The owner chose and iterated the look with a working prototype. The prototype is the
visual reference:
[`assets/2026-10-22-lookup-prototype.html`](assets/2026-10-22-lookup-prototype.html) (fake data,
CDN libraries).

## What the visitor sees

### Landing (everything the owner decided)

- **Background:** a full-screen world map made of cyan dots (real land shapes), gently twinkling,
  with scanlines and a vignette. Random **attacks** cross it constantly as red comets: a bright
  head and a faint trail, from one random land point to another, each ending in a small cyan
  ripple where it is "blocked". Up to about 40 at once.
  - Spawning happens in the animation loop, so nothing piles up while the tab is hidden; this was
    a bug in the prototype.
- **Centre:** the title `Mikro`**`Block`**`List` (Block in red), a small tagline, and a large
  Google-style search box. The box is pill-shaped with a cyan glow and a big round cyan search
  button with a clear magnifier icon (drawn as SVG, not a glyph).
- **Under the box:**
  - a short sentence on what you can do here (check an IPv4/IPv6 address or a CIDR range: is it
    listed, in which variants, from which sources), with two clickable example IPs;
  - a visible privacy line: *"your search never leaves your browser"*.
- **Footer:** real live numbers from the published `stats.json`: IPv4 and IPv6 entries, time of
  the last update, and number of sources. Plus the DB-IP attribution, the license note
  (home / non-commercial use), and links to the repo and README.
- **Ticker** (corner, SOC-style): real entries taken at random from the published list, scrolling
  in one by one as `▲ 45.141.x.x · 🇧🇷 Brasil · IPsum · attack`.
  - It is honest: these are listed addresses, not live traffic. Its label must not claim "live
    attacks"; something like "on the list right now" is fine.

### Searching (Enter or the button)

1. **Scan phase (~1 s):**
   - the search box border turns into a rotating cyan/red light ring, and the button pulses;
   - a wave expands from the box over the map, lighting up the dots it crosses;
   - a thin progress bar and a status line count up:
     `> scanning 28,910 / 39,480 entries · 7 sources`.
2. **Listed:**
   - a red wave goes out, and the status line reads "match found";
   - a thick red comet flies from the IP's **real country** on the map to the search box;
   - on impact the screen flashes briefly, and a red **BLOCKED** card appears. It shows:
     - the IP;
     - the country flag and name;
     - the containing published entry (`inside 185.220.100.0/22`);
     - variant pills (full, lite, IPv6), on or off;
     - each source as a link to its URL, with a category badge (attack / C2);
     - a copy-IP button;
     - "Report a false positive", which opens the GitHub `false_positive.yml` issue form with the
       IP pre-filled.
3. **Not listed:** a green wave, "no match", and a green **NOT ON THE LIST** card.
4. **Invalid input:** a short inline error; no scan animation.
5. The URL becomes `?ip=<query>` (history replaceState), so results can be shared; loading a page
   with `?ip=` runs the search automatically.
6. **CIDR input** (`1.2.3.0/24`) reports every published entry that overlaps it, with the same
   card listing them (cap the list, e.g. first 20 + "and N more").

### Everywhere

- **Language:** Spanish or English, picked from the browser language, with an ES/EN toggle.
  All UI strings live in one table.
- **Always dark:** no light theme; the look is the point.
- **Mobile:** works at phone width with the same layout. The map uses fewer dots and fewer
  comets, and the ticker is hidden or collapsed.
- **`prefers-reduced-motion`:** static map, no comets or waves; results appear directly.
- **Accessibility:** the input has a label, results are announced (`aria-live`), and everything
  works by keyboard.

## Data

The page reads data fresh from the `lists` branch at load time
(`https://raw.githubusercontent.com/Psycomy/MikroBlockList/lists/...`, which allows CORS), so the
page itself only needs deploying when its code changes.

### New published file: `lookup.json` (written by the daily build)

One file for the page:
- build time;
- the source table: name, category, URL;
- every **published `full` entry**, IPv4 and IPv6 when IPv6 is published, each with:
  - which sources list it;
  - whether it is also in `lite`;
  - its country code.

The format is the builder's call. Keep it compact, for example arrays of
`[cidr, sourceBitmask, flags, cc]`, because ~40k entries must stay at a few MB at most (raw
GitHub serves it gzip-compressed). It must not slow down or endanger the build:
- produce it after the safety checks;
- a failure only skips `lookup.json` (with a warning, like IPv6), never the lists.

- **Source membership:** published entries are normalized (allowlist subtracted, collapsed), so
  an entry's sources are those whose own networks overlap it. Compute this efficiently: sort and
  bisect, no O(n·m) scan.
- **Country:** DB-IP **IP to Country Lite** (CC BY 4.0; attribution required on the page:
  "IP Geolocation by DB-IP" linking to https://db-ip.com).
  - Download the monthly CSV: `https://download.db-ip.com/free/dbip-country-lite-YYYY-MM.csv.gz`,
    about 4.5 MB gz, with lines `start,end,CC`.
  - Fall back to the previous month's file if the current one is not out yet.
  - Look up the first address of each entry.
  - If DB-IP is unavailable, publish without countries (`cc` empty). The page then shows no flag
    and the comet starts from a random point.

### Country → map position

The page needs a coordinate per country code to start the comet. Ship a small static table in the
page: a country-centroid lat/lon for each ISO code, written into the page source as data.

### Search runs in the browser

- The page downloads `lookup.json` once.
- It parses the IPv4 and IPv6 ranges into sorted numeric start/end arrays (BigInt or 4×32-bit
  for IPv6).
- It answers each query by binary search.
- Nothing is sent anywhere: no analytics, no third-party requests besides GitHub raw and the
  libraries.

### Ticker data

Random entries from `lookup.json`.

## Hosting and repo layout

- **Location:** the page lives in the repo under `site/` (HTML, CSS, JS, the land-shape and
  centroid data). `site/` holds only the page.
- **Deploy:** a `pages` workflow publishes `site/` to GitHub Pages with the official
  `actions/deploy-pages`, on pushes to `main` that touch `site/**` and on manual dispatch.
  - Enabling Pages (source: GitHub Actions) is a one-time repo setting; the owner authorizes repo
    settings.
  - The URL is `https://psycomy.github.io/MikroBlockList/`.
- **Libraries** (d3-geo, topojson-client, the world-atlas land shape):
  - vendored into `site/` or loaded from jsdelivr with exact versions; prefer vendoring, so the
    page works even if a CDN is down;
  - the land shape can also be pre-rendered to a dot mask at build time instead.
- **Links in:**
  - README: a badge or link near the top, EN and ES;
  - `false_positive.yml`: "check the IP first at <page>";
  - `docs/maintenance.md`: a mention.
- **CHANGELOG** entry under `[Unreleased]`. The router script is unchanged, so there is no
  version bump.

## Goals / non-goals / anti-goals

- **Goals:**
  - a correct answer for any IPv4, IPv6 or CIDR;
  - a spectacular, smooth look (60 fps on a normal laptop);
  - fast first paint: show the map and the box before `lookup.json` arrives, and show
    "loading list…" in the status line until it does;
  - honest wording.
- **Non-goals:**
  - live attack feeds;
  - history of an IP ("listed since…");
  - geolocation of IPs that are not listed;
  - user accounts;
  - a backend.
- **Anti-goals:**
  - sending the searched IP to any server;
  - claiming the comets or ticker are live attacks;
  - a page that freezes the browser (large parsing must not block the first frames; parse in
    chunks or a Web Worker);
  - breaking the daily list publish because of the page's data.

## Tests

- **Python unit tests** for the `lookup.json` generation:
  - source membership on overlapping and collapsed entries;
  - lite flag;
  - IPv6 present and withheld;
  - DB-IP parsing and the missing-DB fallback;
  - size stays reasonable for 40k entries.
- **JS logic** (parsing, IPv4/IPv6/CIDR matching, `?ip=` handling): small pure functions with a
  test that runs in CI using Node's built-in test runner. Node is preinstalled on the runner; add
  a step to the `test` job.
- **Manual check** in a browser: desktop and phone width, reduced motion, both languages, a hidden
  tab coming back.

## Left to the builder

- exact file format;
- JS structure;
- vendoring details;
- the centroid table source (any public-domain dataset, with attribution if needed);
- exact wording and translations, within the tone of the prototype;
- the size and position of the ticker;
- performance tuning.

## Calls made after the builder check (designer's calls, not the owner's)

- **Variants per address:** `lookup.json` carries the published **full and lite** entries of each
  family as separate range sets. Lite is normalized on its own, so a full entry's CIDR can differ
  from lite's. A query is "in lite" when a lite entry covers it.
  - The card's pills are `full` and `lite`, plus a family label (IPv4/IPv6). No "IPv6" on/off pill.
- **Membership:** a source counts for an entry when one of its networks from **today's
  successful fetch** overlaps the entry. Errored sources are ignored.
  - The format allows any number of sources, so there is no 32-bit cap: a list of source indexes
    is fine.
- **Honest unknown states** (amber, never green):
  - **IPv6 withheld that day** (`lookup.json` says so): an IPv6 query reads "IPv6 list not
    published today".
  - **`lookup.json` fails to load:** "list unavailable", with a retry button.
  - **Stale `lookup.json`** (older than 2 days): the result is shown with a warning line.
- **One source of numbers:** every number on the page comes from `lookup.json`, so they always
  agree:
  - the footer counts, the update time and the scan counter;
  - "sources" = sources that contributed entries today. `lookup.json` lists every enabled source
    with its entry count.
  - `stats.json` is not used.
- **CIDR queries:**
  - query inside one entry → BLOCKED;
  - query overlapping one or more entries → amber **PARTIALLY LISTED**, "N listed entries overlap
    this range", listing them (first 20 + "and N more");
  - nothing → NOT ON THE LIST;
  - a single IP is covered by at most one entry per variant (normalization collapses overlaps).
- **False-positive link:** pre-fills `address` (the query), `family`, `variant` (`full`, or
  `lite` if only lite) and `source` (the first listing source) via issue-form URL parameters.
  - A unit test checks that every source in `sources.toml` is an option of the form's `source`
    dropdown, so a new source cannot silently break the pre-fill. The form currently lacks
    `c2intel`: add it.
- **Country:**
  - each entry gets the DB-IP country of its **first** address;
  - if DB-IP maps the entry's range to more than one country, `cc` is empty (shown as "several
    countries"; the comet starts at a random point);
  - the DB-IP month used is recorded in `lookup.json` and shown in the attribution.
- **DB-IP download:**
  - cached per month with `actions/cache`, keyed on `YYYY-MM`, so db-ip.com is hit about once a
    month;
  - fall back to the previous month when the current file is not out yet;
  - without either, publish without countries.
- **Size budget:** `lookup.json` at most 3 MB on the wire (gzip), tested with a 40k-entry
  synthetic list.
  - Parsing must not block the first frames: chunked parsing or a Web Worker, the builder's
    choice.
- **Hook point:** a new optional step at the end of `build()`, in its own try/except like IPv6 (a
  failure skips only `lookup.json`, with a warning), and a separate render function. Existing
  `write_outputs` tests stay valid.
- **Pages workflow:**
  - permissions `pages: write` and `id-token: write`, with the `github-pages` environment;
  - the Node tests join the `test` job of `build.yml`, which already runs on every PR;
  - a `site/`-only push to `main` republishing the lists is harmless and left as is.

## Source attribution (owner's decision after reviewing the terms)

The owner reviewed the source terms on 2026-10-22 and decided to **show every source per IP**.
- Naming the source of each listed IP adds no exposure beyond the republication the project
  already does.
- For Spamhaus (DROP FAQ: name Spamhaus as the source of the data) and ThreatCluster (CC BY:
  credit and link) it fulfils their attribution terms.

Conditions:
- **Spamhaus as data attribution only.** The Spamhaus name appears only as the source of an IP's
  data: on the result card and in the source table. It never appears in headings, the tagline,
  the ticker label or any promotional wording; Spamhaus DROP Terms §3.2 forbid its use in
  promotional material. The ticker may show source names next to an entry: that is data
  attribution.
- **Fix that ships with this work: NOTICE.md lacks the Spamhaus copyright.** The DROP FAQ asks
  redistributors to keep Spamhaus' copyright statement and date/time stamps, and NOTICE.md does
  not do that today.
  - The build keeps, for each Spamhaus source, the copyright line and the date from the
    downloaded file:
    - `drop.txt` header: `; Spamhaus DROP List YYYY/MM/DD - (c) YYYY The Spamhaus Project SLU`
      plus `Last-Modified`;
    - `drop_v6.json` metadata record: `copyright` and `timestamp`.
  - NOTICE.md reproduces them in Spamhaus' row or section. `lookup.json` carries them too, and
    the page shows them in its source table.
  - If the parser cannot find them, the build still publishes, and NOTICE shows the static line
    "(c) The Spamhaus Project SLU" with the fetch time.
- **Per-source terms visible:** the page's source table links to each source and shows its
  `license_note`.
