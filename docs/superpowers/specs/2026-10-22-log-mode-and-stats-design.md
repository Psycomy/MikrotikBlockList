# Log-only mode and daily drop counters (3.5.0)

## Goal

1. **Log-only mode**: let a user try the blocklist without blocking anything, see what *would*
   be blocked, then switch to blocking.
2. **Drop counters**: one log line per update saying how many packets the MBL rules dropped (or
   would have dropped) since the previous report.

## Log-only mode

### Setting

- `:global mblMode "block"` (default) or `"log"`, set before `/import install.rsc`, like
  `mblVariant`. Invalid value → `:error "MBL: invalid mblMode \"x\" (use \"block\" or \"log\"). Nothing was changed."`
  before any change (step 1).
- Persisted like the variant: the stored `mbl-update` gets `:local mode "@MBL_MODE@"`, injected
  with `$mblInject`. On a reinstall with the global unset, the installer reads the
  `:local mode "` value back from the installed `mbl-update` (`block"` / `log"`); fallback `block`.
- `mblMode` is only read, never cleared by the installer (same as `mblVariant`).

### Rules

Comments and order are unchanged (`MBL: in`, `MBL: out`, `MBL: router-out`, the allow rules), so
`mbl-update`'s rule switching and guards work in both modes. Only the action of the three drop
rules changes, in both `/ip firewall raw` and `/ipv6 firewall raw`:

| Rule | block (today) | log |
|---|---|---|
| `MBL: in` | `action=drop` | `action=passthrough` (counted only: inbound scanners would flood the log) |
| `MBL: out` | `action=drop log=yes log-prefix="MBL-OUT"` | `action=log log-prefix="MBL-OUT"` |
| `MBL: router-out` | `action=drop` | `action=log log-prefix="MBL-ROUTER"` |

`out` and `router-out` are the false-positive candidates (a LAN device or the router itself
reaching a listed address), so those are logged; nothing is dropped in log mode.

Switching mode = reinstall with `:global mblMode "block"` (or `"log"`); the gap-free reinstall
already replaces the rules.

### Messages

- The install message always names the mode:
  `MBL: installed (script 3.5.0, variant full, ipv6 no, mode block)`; same for the warning
  variant. (README, bug template and e2e assertions updated.)
- In log mode every non-boot `mbl-update` run logs a warning reminder:
  `MBL: log-only mode, nothing is blocked (reinstall with :global mblMode "block" to block)`.

## Drop counters

At the end of every `mbl-update` run that holds the lock, is **not** a boot run (`$boot`) and is
**not** the installer's first load (`$owned`), in a `:do { } on-error={}` so it can never fail
an update:

1. For each family whose rules exist (IPv4 always; IPv6 when `$ipv6 = "yes"`), read the `packets`
   counter of `MBL: in`, `MBL: out`, `MBL: router-out` (first match of each comment), then
   `reset-counters` those three rules.
2. Log one info line:
   - block: `MBL: dropped since <since>: in N, out N, router-out N packets`
   - log: `MBL: would have dropped since <since>: in N, out N, router-out N packets`
   - with IPv6 on, append `; ipv6 in N, out N, router-out N`.
3. `<since>` is `:global mblStatsSince` (`YYYY-MM-DD HH:MM:SS`, from `/system clock`), then set
   to now. Unset (after a reboot) → `boot`. The installer sets it to the install time after
   adding the rules, since new rules start from zero.

It runs whether or not the download/load of that run succeeded (counters do not depend on it).
The uninstaller already removes every `^mbl` global.

## Tests (e2e, CHR)

- `mblMode "log"` install: the three drop rules have the log-mode actions (IPv4, and IPv6 in the
  IPv6 group), install message ends `mode log)`, `mbl-update` logs the reminder.
- Reinstall without the global keeps `log`; `mblMode "block"` restores `drop` actions; invalid
  value aborts with nothing changed (rules untouched).
- Counters: ping from the router to an address of the active list (`router-out`), run
  `mbl-update`, the log line reports `router-out` >= the pings sent; a second run reports
  `router-out 0` (reset worked). The phrase is `dropped` in block mode and `would have dropped`
  in log mode.
- Boot run (`mblBoot true`) logs no counter line.
- Existing assertions on the install message updated for `, mode block)`.

## Docs

README (EN + ES): "Try it first: log-only mode" under Install, the counter line under "See what is
blocked", the install message examples. CHANGELOG 3.5.0. `VERSION` / `mblScriptVersion` 3.5.0.
