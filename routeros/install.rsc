# MikrotikBlockList v3 - RouterOS v7 installer
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
# Blocklist URL base. Forks: change this line only.
:local mblBase "https://raw.githubusercontent.com/Psycomy/MikrotikBlockList/lists"
# Test/dev only: set :global mblUrlBase before /import to use another server.
:global mblUrlBase
:if ([:len $mblUrlBase] > 0) do={
  :set mblBase $mblUrlBase
  :put "MBL: using test URL base $mblUrlBase"
  :log warning "MBL: using test URL base $mblUrlBase"
}
# The router downloads a plain list (one address per line) and validates
# every line as data; nothing downloaded is ever executed.
:local mblUrl ($mblBase . "/routeros-full.txt")
# Minimum RouterOS version (major.minor). 7.21 is the first release with the
# per-service built-in CA store (/certificate settings builtin-trust-store,
# 7.21 changelog). Tested on CHR 7.24.5.
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
# The address lists are kept so a reinstall never leaves the router
# unprotected: the new rules point at the list that already has entries.
# Files are kept too: v2 boot copies (mbl-*.rsc) are removed by mbl-update
# only after its first successful load.
:local prevList ""
:local prevIn [/ip firewall raw find where comment="MBL: in"]
:if ([:len $prevIn] > 0) do={ :set prevList [/ip firewall raw get ($prevIn->0) src-address-list] }
/system scheduler remove [find where name~"^mbl-"]
/system script remove [find where name~"^mbl-"]
/ip firewall raw remove [find where comment~"^MBL:"]
:local na [:len [/ip firewall address-list find where list="mbl-a"]]
:local nb [:len [/ip firewall address-list find where list="mbl-b"]]
# active = the list with entries (the previous one if both have entries).
# On a clean install both are empty: active = mbl-b, so the first load goes
# into mbl-a and the next update into mbl-b.
:local active "mbl-b"
:if ($na > 0 && ($nb = 0 || $prevList != "mbl-b")) do={ :set active "mbl-a" }
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
# MikrotikBlockList v3 updater - installed by install.rsc, do not edit.
# Normal run: download the plain list, read it in chunks and add each valid
# line to the inactive list (mbl-a or mbl-b), switch the MBL rules to it,
# empty the old list.
# Boot run (:global mblBoot true): same, but from mbl-last.txt, no download.
# Nothing read from the file is ever executed: each line is only a value,
# checked against the a.b.c.d[/p] form, :toip and the prefix range.
:local url "@MBL_URL@"
:local minSize 100000
:local minEntries 1000
# /file read returns at most 32768 bytes per call (RouterOS 7.24)
:local chunkSize 32768
# a longer line cannot be an address; it is dropped as one invalid line
:local maxLine 255
# warn when the loaded list was generated more than this many days ago
:local maxAgeDays 3
:global mblRunning
:global mblBoot
:global mblLastOk
# Rename file $1 to $2 (/file set name=), falling back to copy + remove.
# Run through :parse so a release lacking a command fails at run time,
# not when the whole script is parsed. Returns true on success.
:local mblMove do={
  :do {
    :local f [:parse ("/file set [find where name=\"" . $1 . "\"] name=\"" . $2 . "\"")]
    $f
  } on-error={
    :do {
      :local f [:parse ("/file copy [find where name=\"" . $1 . "\"] name=\"" . $2 . "\"")]
      $f
      /file remove [find where name=$1]
    } on-error={}
  }
  :delay 1s
  :return ([:len [/file find where name=$2]] > 0)
}
# Copy file $1 to $2 (e.g. RAM -> flash/). Returns true only if $2 exists
# with the same size as $1; a short copy (flash full) is removed.
:local mblCopy do={
  :do {
    :local f [:parse ("/file copy [find where name=\"" . $1 . "\"] name=\"" . $2 . "\"")]
    $f
  } on-error={}
  :delay 1s
  :local ok false
  :do {
    :if ([/file get [find where name=$2] size] = [/file get [find where name=$1] size]) do={ :set ok true }
  } on-error={}
  :if (!$ok) do={ /file remove [find where name=$2] }
  :return $ok
}
# "2026-10-19" -> days since 0000-03-01 (proleptic Gregorian), so that the
# difference of two dates is the number of days between them. Leading zeros
# are stripped before :tonum.
:local mblDays do={
  :local num do={
    :local s $1
    :while ([:len $s] > 1 && [:pick $s 0] = "0") do={ :set s [:pick $s 1 [:len $s]] }
    :return [:tonum $s]
  }
  :local y [$num [:pick $1 0 4]]
  :local m [$num [:pick $1 5 7]]
  :local d [$num [:pick $1 8 10]]
  :if ($m <= 2) do={ :set y ($y - 1); :set m ($m + 12) }
  :return ($y * 365 + $y / 4 - $y / 100 + $y / 400 + (153 * ($m - 3) + 2) / 5 + $d - 1)
}
# Value of "key=" in header line $1 (fields separated by spaces), "" if absent.
:local mblField do={
  :local h (" " . $1 . " ")
  :local p [:find $h (" " . $2 . "=")]
  :if ([:typeof $p] != "num") do={ :return "" }
  :local v [:pick $h ($p + [:len $2] + 2) [:len $h]]
  :return [:pick $v 0 [:find $v " "]]
}
:local boot ($mblBoot = true)
:set mblBoot false
:if ($mblRunning = true) do={
  :log warning "MBL: update already running, skipped"
} else={
  :set mblRunning true
  :set mblLastOk false
  # Every failure path logs, cleans up and raises :error, caught below so
  # that the lock is always released.
  :do {
    # Devices with a flash/ directory only keep flash/ across reboots. There
    # the download goes to the RAM root (no flash wear, no flash space used by
    # a file that may be rejected); only a validated file is copied to flash/.
    :local dir ""
    :if ([:len [/file find where name="flash"]] > 0) do={ :set dir "flash/" }
    :local newFile "mbl-new.txt"
    :local lastFile ($dir . "mbl-last.txt")
    :local tmpFile ($dir . "mbl-tmp.txt")
    # ---- source file
    :local fname $newFile
    :if ($boot) do={
      :set fname $lastFile
      # an interrupted boot-copy update may have left only the temp copy
      :if ([:len [/file find where name=$fname]] = 0 && [:len [/file find where name=$tmpFile]] > 0) do={
        :set fname $tmpFile
      }
      :if ([:len [/file find where name=$fname]] = 0) do={
        :log warning "MBL: boot: no $lastFile yet, nothing to load"
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

    # ---- load into the list the rules are NOT using
    :local target "mbl-a"
    :local inRule [/ip firewall raw find where comment="MBL: in"]
    :if ([:len $inRule] > 0) do={
      :if ([/ip firewall raw get ($inRule->0) src-address-list] = "mbl-a") do={
        :set target "mbl-b"
      }
    }
    :local old "mbl-a"
    :if ($target = "mbl-a") do={ :set old "mbl-b" }
    /ip firewall address-list remove [find where list=$target]

    # Read the file in chunks. A line cut at the end of a chunk is carried
    # over to the next one. $reason is set on the first fatal problem.
    :local reason ""
    :local gen "unknown"
    :local entries -1
    :local footer -1
    :local first true
    :local skip false
    :local added 0
    :local bad 0
    :local off 0
    :local carry ""
    :while ($off < $fsize && $reason = "") do={
      :local d ""
      :do {
        :set d ([/file read file=$fname offset=$off chunk-size=$chunkSize as-value]->"data")
      } on-error={}
      :if ([:len $d] = 0) do={
        # read error: stop here, the missing footer rejects the file
        :set off $fsize
      } else={
        :set off ($off + [:len $d])
      }
      :local buf ($carry . $d)
      # the last line may lack its "\n"
      :if ($off >= $fsize && [:len $buf] > 0 && [:pick $buf ([:len $buf] - 1)] != "\n") do={
        :set buf ($buf . "\n")
      }
      :local s 0
      :local e [:find $buf "\n" -1]
      :while ([:typeof $e] = "num" && $reason = "") do={
        :local ln [:pick $buf $s $e]
        :set s ($e + 1)
        :set e [:find $buf "\n" ($s - 1)]
        :if ($skip) do={
          # rest of an over-long line, already counted
          :set skip false
        } else={
          # strip trailing "\r" and spaces
          :local n [:len $ln]
          :while ($n > 0 && ([:pick $ln ($n - 1)] = "\r" || [:pick $ln ($n - 1)] = " ")) do={ :set n ($n - 1) }
          :if ($n < [:len $ln]) do={ :set ln [:pick $ln 0 $n] }
          :if ($first) do={
            :set first false
            :if ([:pick $ln 0 20] != "# MikrotikBlockList ") do={
              :set reason "no header"
            } else={
              :local en [$mblField $ln "entries"]
              :if ([$mblField $ln "format"] != "1" || [$mblField $ln "family"] != "ipv4" || !($en ~ "^[0-9]+\$")) do={
                :set reason "bad header"
              } else={
                :set entries [:tonum $en]
                :local g [$mblField $ln "generated"]
                :if ([:len $g] > 0) do={ :set gen $g }
              }
            }
          } else={
            :if ($footer < 0 && [:pick $ln 0 18] = "# MBL-END entries=" && [:pick $ln 18 [:len $ln]] ~ "^[0-9]+\$") do={
              :set footer [:tonum [:pick $ln 18 [:len $ln]]]
            } else={
              :local ok false
              :if ($footer < 0 && $ln ~ "^[0-9]{1,3}\\.[0-9]{1,3}\\.[0-9]{1,3}\\.[0-9]{1,3}(/[0-9]{1,2})?\$") do={
                :local sl [:find $ln "/"]
                :local ip $ln
                :local plen 32
                :if ([:typeof $sl] = "num") do={
                  :set ip [:pick $ln 0 $sl]
                  :set plen [:tonum [:pick $ln ($sl + 1) [:len $ln]]]
                }
                :if ([:typeof [:toip $ip]] = "ip" && $plen >= 8 && $plen <= 32) do={
                  :do {
                    /ip firewall address-list add list=$target address=$ln timeout=7d
                    :set added ($added + 1)
                    :set ok true
                  } on-error={}
                }
              }
              :if (!$ok) do={ :set bad ($bad + 1) }
            }
          }
        }
      }
      :set carry [:pick $buf $s [:len $buf]]
      :if ([:len $carry] > $maxLine) do={
        # an over-long first line cannot be the header
        :if ($first) do={ :set reason "no header" }
        :if (!$skip) do={ :set bad ($bad + 1) }
        :set carry ""
        :set skip true
      }
    }
    :if ($reason = "") do={
      :if ($footer < 0) do={
        :set reason "no footer"
      } else={
        :if ($footer != $entries) do={
          :set reason "count mismatch"
        } else={
          :if (($bad * 100) > $entries) do={
            :set reason "too many invalid lines ($bad)"
          } else={
            :if ($added != $entries) do={
              :set reason "count mismatch"
            } else={
              :if ($added < $minEntries) do={ :set reason "too few entries ($added)" }
            }
          }
        }
      }
    }
    :if ($reason != "") do={
      /ip firewall address-list remove [find where list=$target]
      :if (!$boot) do={ /file remove [find where name=$fname] }
      :log error "MBL: $fname rejected ($reason), active list kept"
      :error "MBL: abort"
    }
    :local n $added

    # ---- switch rules, then empty the old list
    /ip firewall raw set [find where comment="MBL: in"] src-address-list=$target
    /ip firewall raw set [find where comment="MBL: out"] dst-address-list=$target
    /ip firewall raw set [find where comment="MBL: router-out"] dst-address-list=$target
    /ip firewall address-list remove [find where list=$old]

    # ---- keep the new file as the boot copy
    # new -> tmp first; the old boot copy is only removed once tmp exists,
    # so a valid boot copy (last or tmp) is never lost.
    :if (!$boot) do={
      # recover a temp copy left by an earlier failed rename
      :if ([:len [/file find where name=$lastFile]] = 0 && [:len [/file find where name=$tmpFile]] > 0) do={
        :local rec [$mblMove $tmpFile $lastFile]
      }
      # flash/: RAM -> flash copy, only with room for it (2 x the file size)
      :local room true
      :if ($dir != "") do={
        :local free 0
        :do { :set free [/system resource get free-hdd-space] } on-error={}
        :if ($free <= ($fsize * 2)) do={
          :set room false
          /file remove [find where name=$newFile]
          :log warning "MBL: not enough flash space for the boot copy ($free bytes free, need more than 2 x $fsize), keeping the previous $lastFile"
        }
      }
      :if ($room) do={
        /file remove [find where name=$tmpFile]
        :local saved false
        :if ($dir = "") do={
          :set saved [$mblMove $newFile $tmpFile]
        } else={
          :set saved [$mblCopy $newFile $tmpFile]
          /file remove [find where name=$newFile]
        }
        :if ($saved) do={
          /file remove [find where name=$lastFile]
          :if (![$mblMove $tmpFile $lastFile]) do={
            :log warning "MBL: could not rename $tmpFile to $lastFile, boot will use $tmpFile"
          }
        } else={
          /file remove [find where name=$newFile]
          :log warning "MBL: could not save the boot copy, keeping the previous $lastFile"
        }
      }
    }

    :set mblLastOk true
    :log info "MBL: loaded $n entries into $target (list generated $gen)"

    # ---- v2 leftovers: its boot copies are only removed now that a v3
    # load has succeeded, so an upgrade never loses the last good copy.
    :local v2 [/file find where name~"^(flash/)?mbl-.*\\.rsc\$"]
    :if ([:len $v2] > 0) do={
      /file remove $v2
      :log info "MBL: removed v2 files"
    }

    # ---- stale list: the list is loaded either way; this only warns, e.g.
    # when the GitHub Action has stopped. Errors here are ignored so they can
    # never fail an update that already succeeded.
    :do {
      :if ($gen != "unknown") do={
        :local age ([$mblDays [/system clock get date]] - [$mblDays [:pick $gen 0 10]])
        :if ($age > $maxAgeDays) do={ :log warning "MBL: list is $age days old" }
      }
    } on-error={}
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
# Drop rules point at $active (see step 3); mbl-update switches them later.
:local existing [/ip firewall raw find]
:if ([:len $existing] = 0) do={
  /ip firewall raw add chain=prerouting src-address-list=mbl-allow action=accept comment="MBL: allow-in"
  /ip firewall raw add chain=prerouting dst-address-list=mbl-allow action=accept comment="MBL: allow-out"
  /ip firewall raw add chain=prerouting in-interface-list=WAN src-address-list=$active action=drop comment="MBL: in"
  /ip firewall raw add chain=prerouting in-interface-list=LAN dst-address-list=$active action=drop log=yes log-prefix="MBL-OUT" comment="MBL: out"
  /ip firewall raw add chain=output dst-address-list=mbl-allow action=accept comment="MBL: allow-router-out"
  /ip firewall raw add chain=output dst-address-list=$active action=drop comment="MBL: router-out"
} else={
  # Each rule goes just before the user's first rule, so ours keep this order.
  :local anchor ($existing->0)
  /ip firewall raw add chain=prerouting src-address-list=mbl-allow action=accept comment="MBL: allow-in" place-before=$anchor
  /ip firewall raw add chain=prerouting dst-address-list=mbl-allow action=accept comment="MBL: allow-out" place-before=$anchor
  /ip firewall raw add chain=prerouting in-interface-list=WAN src-address-list=$active action=drop comment="MBL: in" place-before=$anchor
  /ip firewall raw add chain=prerouting in-interface-list=LAN dst-address-list=$active action=drop log=yes log-prefix="MBL-OUT" comment="MBL: out" place-before=$anchor
  /ip firewall raw add chain=output dst-address-list=mbl-allow action=accept comment="MBL: allow-router-out" place-before=$anchor
  /ip firewall raw add chain=output dst-address-list=$active action=drop comment="MBL: router-out" place-before=$anchor
}

# -------------------------------------------------------- 8. first load
:global mblRunning
:global mblLastOk
:set mblLastOk false
:if ($mblRunning = true) do={
  :put "MBL: WARNING first load skipped: another mbl-update holds the lock. If none is running, clear it with  :global mblRunning false  and run  /system script run mbl-update"
  :log warning "MBL: first load skipped, lock mblRunning is set (clear with :global mblRunning false)"
} else={
  /system script run mbl-update
}
/file remove [find where name="install.rsc" or name="flash/install.rsc"]
:if ($mblLastOk = true) do={
  :put "MBL: installed"
  :log info "MBL: installed"
} else={
  :put "MBL: WARNING installed, but the first load failed or was skipped. See /log print where message~\"MBL\""
  :log warning "MBL: installed, but the first load failed or was skipped"
}
}
