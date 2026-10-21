# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and versions follow
[Semantic Versioning](https://semver.org/). The version in use is in [`VERSION`](VERSION), and the
published list carries it as `script=<version>` in its header.

## [3.3.0] - 2026-10-21

### Added
- Optional IPv6, off by default. New source `spamhaus-drop-v6` (format `jsonl_cidr`, `full` and `lite`).
  IPv6 sources today: Spamhaus DROPv6 (91 networks), blocklist.de (about 523), Turris (49) and
  ThreatCluster (1): 648 IPv6 entries in `full`, 86 in `lite`.
- `normalize6`: drops non-global IPv6 (ULA, link-local, documentation, multicast, `::/8`,
  IPv4-mapped, NAT64, 6to4, Teredo) and anything broader than /19, subtracts the IPv6 allowlist
  (Cloudflare, GitHub's `2606:50c0::/32`, public DNS) and aggregates.
- New published files: `routeros6-full.txt`, `routeros6-lite.txt`, `blocklist6.txt`,
  `blocklist6-lite.txt` (header `family=ipv6`; `/128` written without mask). IPv6 limits: `full`
  50 to 20,000, `lite` 20 to 5,000, with the 50% drop and 2x growth checks.
- Best effort: if an IPv6 variant fails its checks, no IPv6 file is published that day, with a
  warning on stderr and in the step summary; IPv4 is still published and the exit code stays 0.
  `stats.json` gains `ipv6` (`published`, `variants.<v>.total`) and per-source `entries6`;
  `entries` now counts IPv4 only.
- Installer: `:global mblIpv6 true; ` before the one-liner (combinable with `mblVariant`) creates
  `mbl6-a`, `mbl6-b`, `mbl6-allow`, six `MBL:` rules in `/ipv6 firewall raw` and `mbl6-last.txt`.
  With the global empty the installed choice is kept; `false` removes every MBL IPv6 object (your
  own `mbl6-allow` entries are kept); any other value stops with `:error` before changing anything.
  The uninstaller removes both families.
- `mbl-update` processes `routeros6-<variant>.txt` after the IPv4 update (lines validated with
  `:toip6` and a prefix from 19 to 128, header `family=ipv6`, at least 200 bytes and 50/20
  entries). An IPv6 failure logs `MBL: ipv6 ...` and never touches IPv4 lists, rules or files.
- Final message: `MBL: installed (script 3.3.0, variant <v>, ipv6 <yes|no>)`.
- End-to-end cases `test_14k` to `test_14o`.

### Upgrade from 3.2.0
Routers on 3.2.0 will log the newer-script notice and can reinstall with the install command. They
keep their variant and stay IPv4-only unless `:global mblIpv6 true; ` is set first. The global
persists until reboot, so set it explicitly (or to `""`) when reinstalling in the same session.

## [3.2.0] - 2026-10-21

### Added
- Two variants of the list: `full` (default, 38,573 entries at release) and `lite` (4,308 entries),
  built from Spamhaus DROP, DShield, Emerging Threats compromised, ThreatFox and ThreatCluster.
  Each source in `sources.toml` declares `variants` (default `["full"]`); every `lite` source must
  also be in `full`.
- New published files: `routeros-lite.txt` and `blocklist-lite.txt` (headers carry `variant=lite`).
  `routeros-full.txt`, `blocklist.txt` and the legacy `blocklist.rsc` (full only) are unchanged.
  `stats.json` gains `variants` (`{"full": {"total": N}, "lite": {"total": M}}`); the top-level
  `total` stays equal to `full`.
- Per-variant safety checks: `full` 5,000 to 150,000 entries, `lite` 1,000 to 20,000; in both, no
  drop over 50% and no growth over 2x (`--allow-growth` applies to both) against that variant's
  previous total. If either variant fails, nothing is published. A drop no larger than the previous
  entries of optional sources that failed this run skips only the drop check, with a warning.
- Installer: `:global mblVariant "lite"; ` before the one-liner installs `lite`; `"full"` switches
  back. With the global empty, the installer keeps the installed variant (or uses `full`). Any other
  value stops with `:error` before changing anything.
- `mbl-update` downloads `routeros-<variant>.txt`, requires a file of at least 100,000 bytes (`full`)
  or 20,000 (`lite`), and rejects a header whose `variant=` differs from the installed one (`bad header`).
- Final message: `MBL: installed (script 3.2.0, variant <v>)`.
- End-to-end cases `test_14f` to `test_14j` (install lite, reinstall keeps lite, invalid value,
  variant mismatch, back to full).

### Upgrade from 3.1.0
Routers on 3.1.0 will log the newer-script notice and can reinstall with the install command. They
stay on `full` unless `:global mblVariant "lite"; ` is set first. The global persists until reboot,
so set it explicitly (or to `""`) when reinstalling in the same session.

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
