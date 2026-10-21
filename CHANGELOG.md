# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and versions follow
[Semantic Versioning](https://semver.org/). The version in use is in [`VERSION`](VERSION), and the
published list carries it as `script=<version>` in its header.

## [3.1.0] - 2026-10-21

### Added
- Update notice: after a successful load, `mbl-update` compares the installed script version with the
  one published in the list header and logs a single `warning`
  (`MBL: script <published> available (installed <installed>) - reinstall: ...`) when the published
  one is newer. The comparison is numeric per `MAJOR.MINOR.PATCH` (`3.10.0` is newer than `3.9.0`).
- A published version that is not `MAJOR.MINOR.PATCH` is ignored: no notice and no error. The notice
  never makes a load fail and nothing read from the file is executed.
- The router never updates itself; reinstalling stays a manual step.
- CI check that `VERSION` and the installer version stay in sync.
- End-to-end cases `test_14b` to `test_14e` for the notice.
- The installer's final message now includes the installed script version (`MBL: installed (script 3.1.0)`).

### Upgrade from 3.0.0
Routers installed before 3.1.0 (v2 and 3.0.0) do not contain the version check, so they never show the
newer-script notice. Run the install command once more to get it; later releases are then announced.

## [3.0.0] - 2026-10-21

### Changed
- Safe ingestion: `mbl-update` no longer uses `/import` on the downloaded list. It reads the file in
  chunks and validates every line as an IPv4 address or prefix before adding it, so nothing in the file
  is ever executed. It also checks the header/footer, the entry count and the share of invalid lines
  (rejected above 1 %); a rejected download keeps the active list.
- The list is published as plain text, `lists/routeros-full.txt`; its header carries the script version (`script=`, from the new `VERSION` file).
- The backup of the last good list is `mbl-last.txt` (v2 used `mbl-last.rsc`).

### Added
- End-to-end cases for the new reader: v2 to v3 upgrade, injected lines, count mismatch, CRLF and
  invalid ratio; CI fetches tags so the upgrade test can install the `v2.0.0` script.

### Upgrade from v2
Run the install command again. The installer replaces the v2 updater, the first load removes the old
`mbl-*.rsc` files (`MBL: removed v2 files`) and the active list is never left empty.
`blocklist.rsc` keeps being published unchanged for v2 routers until at least 2027-04-30.

## [2.0.0] - 2026-10-19 (tagged 2026-10-21)

The rewrite landed on 2026-10-19; the `v2.0.0` tag was created on 2026-10-21 and points at the
phase-1 merge (`111382f`), so the items below up to that merge belong to this release.

### Added
- Rewrite of the generator and the RouterOS installer: daily build of an IPv4 blocklist published on the
  `lists` branch, raw-firewall rules on two alternating lists (`mbl-a`/`mbl-b`), schedulers
  `mbl-daily` and `mbl-boot`, an allowlist and an uninstaller. Validated on a CHR with RouterOS 7.24.5
  (minimum supported: 7.21).
- The build refuses to publish when the total more than doubles (2026-10-19).
- Stale-list warning in `mbl-update` (`MBL: list is N days old`), the `--allow-growth` override
  (also a manual `allow_growth` workflow input) and CI on Node 24 actions (PR #1, 2026-10-19).
- Source study applied to `sources.toml` (PR #2, 2026-10-20; see `docs/source-study-2026-10-20.md`).
- RouterOS end-to-end tests on a disposable CHR (QEMU/KVM) in CI, the `routeros-e2e` workflow, and an
  optional `mblUrlBase` global to point the installer at a test server (phase 1, PR #3, 2026-10-21).
