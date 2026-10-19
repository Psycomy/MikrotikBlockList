# MikrotikBlockList v2 - RouterOS v7 installer
# https://github.com/Psycomy/MikrotikBlockList
# For home / non-commercial use only (see source licenses in README)
#
# Usage:
#   /tool fetch url="https://raw.githubusercontent.com/Psycomy/MikrotikBlockList/main/routeros/install.rsc" check-certificate=yes; /import install.rsc
#
# Idempotent: re-running it removes and recreates everything named mbl-* / MBL:*.
# It never touches anything else, except enabling the RouterOS built-in CA
# store for /tool fetch (needed for check-certificate=yes).
#
# Everything runs inside one block so that local variables survive and any
# :error aborts the whole installer.
{
# ---------------------------------------------------------------- settings
# Blocklist URL. Forks: change this line only.
:local mblUrl "https://raw.githubusercontent.com/Psycomy/MikrotikBlockList/lists/blocklist.rsc"
# Minimum RouterOS version (major.minor).
# TODO(Task 9): confirm on CHR. 7.21 = first release with the per-service
# built-in CA store (/certificate settings builtin-trust-store).
:local mblMinVersion "7.21"

# "7.21.3 (stable)" -> 7021 ; "7.19rc2" -> 7019
:local mblVerNum do={
  :local d [:find $1 "."]
  :local maj [:tonum [:pick $1 0 $d]]
  :local rest [:pick $1 ($d + 1) [:len $1]]
  :local e 0
  :while ($e < [:len $rest] && [:pick $rest $e] ~ "[0-9]") do={ :set e ($e + 1) }
  :return ($maj * 1000 + [:tonum [:pick $rest 0 $e]])
}
# 7 -> "07"
:local mblPad do={
  :if ($1 < 10) do={ :return ("0" . $1) }
  :return [:tostr $1]
}

# ------------------------------------------------- 1. pre-checks (no changes)
:local rosVer [/system resource get version]
:local rosNum [$mblVerNum $rosVer]
:if ($rosNum < [$mblVerNum $mblMinVersion] || $rosNum >= 8000) do={
  :error "MBL: RouterOS $rosVer not supported, need v7 >= $mblMinVersion. Nothing was changed."
}
:if ([:len [/interface list find where name="WAN"]] = 0) do={
  :error "MBL: interface list WAN not found (add your Internet interface to /interface list WAN). Nothing was changed."
}
:if ([:len [/interface list find where name="LAN"]] = 0) do={
  :error "MBL: interface list LAN not found (add your LAN interfaces to /interface list LAN). Nothing was changed."
}

# ------------------------------------------- 2. HTTPS: built-in CA for fetch
# builtin-trust-store is "all", "untrusted", "default" (= current-defaults)
# or a list of components. Add "fetch" to it unless already covered.
# Wrapped in :parse so that the script still parses (and the version check
# above reports cleanly) on releases without this property.
:local getTs [:parse ":return [/certificate settings get builtin-trust-store]"]
:local getDefs [:parse ":return [/certificate settings get current-defaults]"]
:local ts [$getTs]
:if ($ts = "default") do={ :set ts [$getDefs] }
:if ($ts != "all" && [:typeof [:find [:tostr $ts] "fetch"]] = "nil") do={
  :local comps "fetch"
  :if ($ts != "untrusted") do={
    :foreach c in=$ts do={ :if ([:len $c] > 0) do={ :set comps ($comps . "," . $c) } }
  }
  :local setTs [:parse "/certificate settings set builtin-trust-store=$comps"]
  $setTs
  :log info "MBL: built-in CA store enabled for fetch ($comps)"
}

# ------------------------------------------ 3. remove a previous installation
/system scheduler remove [find where name~"^mbl-"]
/system script remove [find where name~"^mbl-"]
/ip firewall raw remove [find where comment~"^MBL:"]
/ip firewall address-list remove [find where list="mbl-a"]
/ip firewall address-list remove [find where list="mbl-b"]
# mbl-allow is kept as is (user entries and previous "MBL: admin" entries).

# --------------------------------------------------- 4. admin allowlist
# Current management sessions, so a remote installer never locks itself out.
:foreach s in=[/user active find] do={
  :local a [:tostr [/user active get $s address]]
  :if ([:len $a] > 0) do={
    :do {
      /ip firewall address-list add list=mbl-allow address=$a comment="MBL: admin"
    } on-error={}
  }
}

# --------------------------------------------------- 5. mbl-update script
# The body is stored verbatim; @MBL_URL@ is replaced with $mblUrl below.
/system script add name=mbl-update policy=ftp,read,write,policy,test \
  dont-require-permissions=no comment="MBL: blocklist updater" source={
# MikrotikBlockList v2 updater - installed by install.rsc, do not edit.
# Normal run: download, validate, import into the inactive list (mbl-a or
# mbl-b), switch the MBL rules to it, empty the old list.
# Boot run (:global mblBoot true): same, but from mbl-last.rsc, no download.
:local url "@MBL_URL@"
:local minSize 100000
:local minEntries 1000
:global mblRunning
:global mblBoot
:global mblTarget
:global mblImportOk
:local boot ($mblBoot = true)
:set mblBoot false
:if ($mblRunning = true) do={
  :log warning "MBL: update already running, skipped"
} else={
  :set mblRunning true
  # Every failure path logs, cleans up and raises :error, caught below so
  # that the lock is always released.
  :do {
    # ---- source file
    :local fname "mbl-new.rsc"
    :if ($boot) do={
      :set fname "mbl-last.rsc"
      :if ([:len [/file find where name=$fname]] = 0) do={
        :log warning "MBL: boot: no $fname yet, nothing to load"
        :error "MBL: abort"
      }
    } else={
      /file remove [find where name=$fname]
      :local fetched true
      :do {
        /tool fetch url=$url dst-path=$fname check-certificate=yes
      } on-error={ :set fetched false }
      :if (!$fetched) do={
        /file remove [find where name=$fname]
        :log error "MBL: download failed ($url), list not changed"
        :error "MBL: abort"
      }
      # let the file system catch up before reading the size
      :delay 2s
    }

    # ---- size
    :local fsize 0
    :do { :set fsize [/file get [find where name=$fname] size] } on-error={}
    :if ($fsize < $minSize) do={
      :if (!$boot) do={ /file remove [find where name=$fname] }
      :log error "MBL: $fname too small ($fsize bytes), list not changed"
      :error "MBL: abort"
    }

    # ---- import into the list the rules are NOT using
    :local target "mbl-a"
    :local inRule [/ip firewall raw find where comment="MBL: in"]
    :if ([:len $inRule] > 0) do={
      :if ([/ip firewall raw get ($inRule->0) src-address-list] = "mbl-a") do={
        :set target "mbl-b"
      }
    }
    :local old "mbl-a"
    :if ($target = "mbl-a") do={ :set old "mbl-b" }
    :set mblTarget $target
    :set mblImportOk false
    /ip firewall address-list remove [find where list=$target]
    :do {
      /import file-name=$fname verbose=no
    } on-error={ :log warning "MBL: /import of $fname raised an error" }

    # ---- validate (the file sets mblImportOk on its last line)
    :local n [:len [/ip firewall address-list find where list=$target]]
    :if ($mblImportOk != true || $n < $minEntries) do={
      /ip firewall address-list remove [find where list=$target]
      :if (!$boot) do={ /file remove [find where name=$fname] }
      :log error "MBL: import of $fname failed (complete=$mblImportOk, entries=$n), active list kept"
      :error "MBL: abort"
    }

    # ---- switch rules, then empty the old list
    /ip firewall raw set [find where comment="MBL: in"] src-address-list=$target
    /ip firewall raw set [find where comment="MBL: out"] dst-address-list=$target
    /ip firewall raw set [find where comment="MBL: router-out"] dst-address-list=$target
    /ip firewall address-list remove [find where list=$old]

    # ---- keep the new file as the boot copy
    # Rename via /file set name=, else /file copy. Both run through :parse
    # so a release lacking them fails here at run time, not at parse time.
    :if (!$boot) do={
      /file remove [find where name="mbl-last.rsc"]
      :do {
        :local mv [:parse "/file set [find where name=\"mbl-new.rsc\"] name=\"mbl-last.rsc\""]
        $mv
      } on-error={
        :do {
          :local cp [:parse "/file copy [find where name=\"mbl-new.rsc\"] name=\"mbl-last.rsc\""]
          $cp
          /file remove [find where name="mbl-new.rsc"]
        } on-error={ :log warning "MBL: could not save mbl-last.rsc (boot copy)" }
      }
    }

    :log info "MBL: loaded $n entries into $target"
  } on-error={ :log warning "MBL: update aborted" }
  :set mblRunning false
}
}

# Inject the URL into the stored script.
:local ph "@MBL_URL@"
:local src [/system script get [find where name="mbl-update"] source]
:local p [:find $src $ph]
:if ([:typeof $p] = "nil") do={ :error "MBL: internal error, URL placeholder not found in mbl-update" }
/system script set [find where name="mbl-update"] \
  source=([:pick $src 0 $p] . $mblUrl . [:pick $src ($p + [:len $ph]) [:len $src]])

# --------------------------------------------------------- 6. schedulers
# Daily at a random time so routers do not all hit GitHub at once.
:local r [:rndnum from=0 to=86399]
:local startTime ([$mblPad ($r / 3600)] . ":" . [$mblPad (($r % 3600) / 60)] . ":" . [$mblPad ($r % 60)])
/system scheduler add name=mbl-daily interval=1d start-time=$startTime \
  policy=ftp,read,write,policy,test comment="MBL: daily update" \
  on-event="/system script run mbl-update"
# At boot: reload the last good copy at once (timeout entries do not survive
# a reboot), then try a fresh download once the network is likely up.
/system scheduler add name=mbl-boot start-time=startup \
  policy=ftp,read,write,policy,test comment="MBL: load at boot" \
  on-event={:global mblBoot true; /system script run mbl-update; :delay 60s; /system script run mbl-update}

# ------------------------------------------------- 7. raw rules (at the top)
:local existing [/ip firewall raw find]
:if ([:len $existing] = 0) do={
  /ip firewall raw add chain=prerouting src-address-list=mbl-allow action=accept comment="MBL: allow-in"
  /ip firewall raw add chain=prerouting dst-address-list=mbl-allow action=accept comment="MBL: allow-out"
  /ip firewall raw add chain=prerouting in-interface-list=WAN src-address-list=mbl-a action=drop comment="MBL: in"
  /ip firewall raw add chain=prerouting in-interface-list=LAN dst-address-list=mbl-a action=drop log=yes log-prefix="MBL-OUT" comment="MBL: out"
  /ip firewall raw add chain=output dst-address-list=mbl-a action=drop comment="MBL: router-out"
} else={
  # Each rule goes just before the user's first rule, so ours keep this order.
  :local anchor ($existing->0)
  /ip firewall raw add chain=prerouting src-address-list=mbl-allow action=accept comment="MBL: allow-in" place-before=$anchor
  /ip firewall raw add chain=prerouting dst-address-list=mbl-allow action=accept comment="MBL: allow-out" place-before=$anchor
  /ip firewall raw add chain=prerouting in-interface-list=WAN src-address-list=mbl-a action=drop comment="MBL: in" place-before=$anchor
  /ip firewall raw add chain=prerouting in-interface-list=LAN dst-address-list=mbl-a action=drop log=yes log-prefix="MBL-OUT" comment="MBL: out" place-before=$anchor
  /ip firewall raw add chain=output dst-address-list=mbl-a action=drop comment="MBL: router-out" place-before=$anchor
}

# -------------------------------------------------------- 8. first load
/system script run mbl-update
/file remove [find where name="install.rsc"]
:log info "MBL: installed"
}
