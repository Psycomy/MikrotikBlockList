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
# List variant: "full" (default) or "lite" (a shorter list for small
# routers). Set :global mblVariant "lite" before /import to choose it; when
# unset, a reinstall keeps the variant already installed. See step 1.
:global mblVariant
# IPv6 lists and rules: off by default. Set :global mblIpv6 true before
# /import to add them (false removes them); when unset, a reinstall keeps the
# choice already installed. See step 1.
:global mblIpv6
# Minimum RouterOS version (major.minor). 7.21 is the first release with the
# per-service built-in CA store (/certificate settings builtin-trust-store,
# 7.21 changelog). Tested on CHR 7.24.5.
:local mblMinVersion "7.21"
# Version of this installer and of the mbl-update it installs (= VERSION file).
# mbl-update logs a warning when the published list says a newer one exists.
:local mblScriptVersion "3.3.0"

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
# Variant: :global mblVariant if set, else the one in the installed
# mbl-update (its ':local variant "<v>"' line, read before step 3 removes
# it), else full. Only "full" or "lite" is ever used.
:local mblVar ""
:local want [:tostr $mblVariant]
:if ([:len $want] > 0) do={
  :if ($want != "full" && $want != "lite") do={
    :error "MBL: invalid mblVariant \"$want\" (use \"full\" or \"lite\"). Nothing was changed."
  }
  :set mblVar $want
}
# IPv6: :global mblIpv6 (true/false, boolean or string) if set, else the
# choice in the installed mbl-update (its ':local ipv6 "<yes|no>"' line), else
# off. Only "yes" or "no" is ever used.
:local mblV6 ""
:local want6 [:tostr $mblIpv6]
:if ([:len $want6] > 0) do={
  :if ($want6 != "true" && $want6 != "false") do={
    :error "MBL: invalid mblIpv6 \"$want6\" (use true or false). Nothing was changed."
  }
  :set mblV6 "no"
  :if ($want6 = "true") do={ :set mblV6 "yes" }
}
:local prev [/system script find where name="mbl-update"]
:if ([:len $prev] > 0) do={
  :local prevSrc [/system script get ($prev->0) source]
  :if ($mblVar = "") do={
    :local key ":local variant \""
    :local q [:find $prevSrc $key]
    :if ([:typeof $q] = "num") do={
      :local v [:pick $prevSrc ($q + [:len $key]) ($q + [:len $key] + 5)]
      :if ($v = "full\"") do={ :set mblVar "full" }
      :if ($v = "lite\"") do={ :set mblVar "lite" }
    }
  }
  :if ($mblV6 = "") do={
    :local key ":local ipv6 \""
    :local q [:find $prevSrc $key]
    :if ([:typeof $q] = "num") do={
      :local v [:pick $prevSrc ($q + [:len $key]) ($q + [:len $key] + 4)]
      :if ($v = "yes\"") do={ :set mblV6 "yes" }
      :if ([:pick $v 0 3] = "no\"") do={ :set mblV6 "no" }
    }
  }
}
:if ($mblVar = "") do={ :set mblVar "full" }
:if ($mblV6 = "") do={ :set mblV6 "no" }
# The router downloads a plain list (one address per line) and validates
# every line as data; nothing downloaded is ever executed.
:local mblUrl ($mblBase . "/routeros-" . $mblVar . ".txt")
:local mblUrl6 ($mblBase . "/routeros6-" . $mblVar . ".txt")

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
# IPv6, the same way with mbl6-a / mbl6-b. With IPv6 off, every MBL IPv6
# object of an earlier installation goes: rules, lists, "MBL: admin" entries
# in mbl6-allow (your own entries there are kept) and mbl6-* files.
:local prevList6 ""
:local prevIn6 [/ipv6 firewall raw find where comment="MBL: in"]
:if ([:len $prevIn6] > 0) do={ :set prevList6 [/ipv6 firewall raw get ($prevIn6->0) src-address-list] }
/ipv6 firewall raw remove [find where comment~"^MBL:"]
:local active6 "mbl6-b"
:if ($mblV6 = "yes") do={
  :local na6 [:len [/ipv6 firewall address-list find where list="mbl6-a"]]
  :local nb6 [:len [/ipv6 firewall address-list find where list="mbl6-b"]]
  :if ($na6 > 0 && ($nb6 = 0 || $prevList6 != "mbl6-b")) do={ :set active6 "mbl6-a" }
} else={
  /ipv6 firewall address-list remove [find where list="mbl6-a" or list="mbl6-b"]
  /ipv6 firewall address-list remove [find where list="mbl6-allow" and comment="MBL: admin"]
  /file remove [find where name~"^(flash/)?mbl6-.*\\.txt\$"]
}

# --------------------------------------------------- 4. admin allowlist
# Current management sessions, so a remote installer never locks itself out.
:foreach s in=[/user active find] do={
  :local a [:tostr [/user active get $s address]]
  :if ([:len $a] > 0) do={
    :if ([:typeof [:find $a ":"]] = "num") do={
      # an IPv6 session: mbl6-allow, only with IPv6 on
      :if ($mblV6 = "yes") do={
        :do {
          /ipv6 firewall address-list add list=mbl6-allow address=$a comment="MBL: admin"
        } on-error={}
      }
    } else={
      :do {
        /ip firewall address-list add list=mbl-allow address=$a comment="MBL: admin"
      } on-error={}
    }
  }
}

# --------------------------------------------------- 5. mbl-update script
# The body is stored verbatim; @MBL_URL@, @MBL_URL6@, @MBL_VERSION@,
# @MBL_VARIANT@ and @MBL_IPV6@ are replaced with $mblUrl, $mblUrl6,
# $mblScriptVersion, $mblVar and $mblV6 below.
/system script add name=mbl-update policy=ftp,read,write,policy,test \
  dont-require-permissions=no comment="MBL: blocklist updater" source={
# MikrotikBlockList v3 updater - installed by install.rsc, do not edit.
# Normal run: download the plain list, read it in chunks and add each valid
# line to the inactive list (mbl-a or mbl-b), switch the MBL rules to it,
# empty the old list.
# Boot run (:global mblBoot true): same, but from mbl-last.txt, no download.
# With IPv6 on, the IPv6 list then goes the same way into mbl6-a / mbl6-b
# (files mbl6-*.txt, rules in /ipv6 firewall raw). An IPv6 failure never
# touches anything IPv4: each family has its own lists, rules and files.
# Nothing read from the file is ever executed: each line is only a value,
# checked against the address form, :toip / :toip6 and the prefix range.
:local url "@MBL_URL@"
:local url6 "@MBL_URL6@"
:local scriptVersion "@MBL_VERSION@"
# the list header must name this variant
:local variant "@MBL_VARIANT@"
# "yes": also load the IPv6 list
:local ipv6 "@MBL_IPV6@"
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
# true if version $1 is newer than version $2, compared numerically by
# MAJOR.MINOR.PATCH component (3.10.0 > 3.9.0). false when either one is not
# of that form. Nothing is parsed or executed: only :tonum per component.
:local mblVerGt do={
  :local re "^[0-9]+\\.[0-9]+\\.[0-9]+\$"
  :if (!($1 ~ $re) || !($2 ~ $re)) do={ :return false }
  :local num do={
    :local s $1
    :while ([:len $s] > 1 && [:pick $s 0] = "0") do={ :set s [:pick $s 1 [:len $s]] }
    :return [:tonum $s]
  }
  :local a ($1 . ".")
  :local b ($2 . ".")
  :local pa -1
  :local pb -1
  :for i from=1 to=3 do={
    :local ea [:find $a "." $pa]
    :local eb [:find $b "." $pb]
    :local x [$num [:pick $a ($pa + 1) $ea]]
    :local y [$num [:pick $b ($pb + 1) $eb]]
    :if ($x > $y) do={ :return true }
    :if ($x < $y) do={ :return false }
    :set pa $ea
    :set pb $eb
  }
  :return false
}
:local boot ($mblBoot = true)
:set mblBoot false
:if ($mblRunning = true) do={
  :log warning "MBL: update already running, skipped"
} else={
  :set mblRunning true
  :set mblLastOk false
  # IPv4 first, then IPv6 when it is on. Each family runs in its own :do, so
  # an IPv6 failure can never change the IPv4 result (mblLastOk) or objects.
  :foreach fam in={"ipv4";"ipv6"} do={
    :local v6 ($fam = "ipv6")
    # "" for IPv4 (its messages are unchanged), "ipv6 " for IPv6
    :local fl ""
    :if ($v6) do={ :set fl "ipv6 " }
    :if (!$v6 || $ipv6 = "yes") do={
      # Every failure path logs, cleans up and raises :error, caught below so
      # that the lock is always released.
      :do {
        # per-family settings
        :local furl $url
        :local fp "mbl-"
        :local la "mbl-a"
        :local lb "mbl-b"
        # minimum file size in bytes; the lite list is much shorter
        :local minSize 100000
        :if ($variant = "lite") do={ :set minSize 20000 }
        :local minEntries 1000
        :local lineRe "^[0-9]{1,3}\\.[0-9]{1,3}\\.[0-9]{1,3}\\.[0-9]{1,3}(/[0-9]{1,2})?\$"
        :local minPlen 8
        :local maxPlen 32
        :if ($v6) do={
          :set furl $url6
          :set fp "mbl6-"
          :set la "mbl6-a"
          :set lb "mbl6-b"
          :set minSize 200
          :set minEntries 50
          :if ($variant = "lite") do={ :set minEntries 20 }
          # hex groups and colons only (at least two colons): never an IPv4 line
          :set lineRe "^[0-9a-fA-F]{0,4}(:[0-9a-fA-F]{0,4}){2,7}(/[0-9]{1,3})?\$"
          :set minPlen 19
          :set maxPlen 128
        }
        # Devices with a flash/ directory only keep flash/ across reboots. There
        # the download goes to the RAM root (no flash wear, no flash space used by
        # a file that may be rejected); only a validated file is copied to flash/.
        :local dir ""
        :if ([:len [/file find where name="flash"]] > 0) do={ :set dir "flash/" }
        :local newFile ($fp . "new.txt")
        :local lastFile ($dir . $fp . "last.txt")
        :local tmpFile ($dir . $fp . "tmp.txt")
        # ---- source file
        :local fname $newFile
        :if ($boot) do={
          :set fname $lastFile
          # an interrupted boot-copy update may have left only the temp copy
          :if ([:len [/file find where name=$fname]] = 0 && [:len [/file find where name=$tmpFile]] > 0) do={
            :set fname $tmpFile
          }
          :if ([:len [/file find where name=$fname]] = 0) do={
            :log warning ("MBL: " . $fl . "boot: no $lastFile yet, nothing to load")
            :error "MBL: abort"
          }
        } else={
          /file remove [find where name=$fname]
          :local fetched true
          :do {
            /tool fetch url=$furl dst-path=$fname check-certificate=yes
          } on-error={ :set fetched false }
          :if (!$fetched) do={
            /file remove [find where name=$fname]
            :log error ("MBL: " . $fl . "download failed ($furl), " . $fl . "list not changed")
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
          :log error ("MBL: " . $fl . "$fname too small ($fsize bytes), " . $fl . "list not changed")
          :error "MBL: abort"
        }

        # ---- load into the list the rules are NOT using
        :local target $la
        :local cur ""
        :if ($v6) do={
          :local inRule [/ipv6 firewall raw find where comment="MBL: in"]
          :if ([:len $inRule] > 0) do={ :set cur [/ipv6 firewall raw get ($inRule->0) src-address-list] }
        } else={
          :local inRule [/ip firewall raw find where comment="MBL: in"]
          :if ([:len $inRule] > 0) do={ :set cur [/ip firewall raw get ($inRule->0) src-address-list] }
        }
        :if ($cur = $la) do={ :set target $lb }
        :local old $la
        :if ($target = $la) do={ :set old $lb }
        :if ($v6) do={
          /ipv6 firewall address-list remove [find where list=$target]
        } else={
          /ip firewall address-list remove [find where list=$target]
        }

        # Read the file in chunks. A line cut at the end of a chunk is carried
        # over to the next one. $reason is set on the first fatal problem.
        :local reason ""
        :local gen "unknown"
        # script version named in the list header; only compared and logged
        :local pubScript ""
        :local entries -1
        :local footer -1
        :local first true
        :local skip false
        :local added 0
        :local bad 0
        :local off 0
        :local carry ""
        # any unexpected error while reading goes through the rejection below
        :do {
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
                    :if ([$mblField $ln "format"] != "1" || [$mblField $ln "family"] != $fam || [$mblField $ln "variant"] != $variant || !($en ~ "^[0-9]+\$")) do={
                      :set reason "bad header"
                    } else={
                      :set entries [:tonum $en]
                      :local g [$mblField $ln "generated"]
                      # only a date-like value is logged or used for the stale check
                      :if ($g ~ "^[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T") do={ :set gen $g }
                      :set pubScript [$mblField $ln "script"]
                    }
                  }
                } else={
                  :if ($footer < 0 && [:pick $ln 0 18] = "# MBL-END entries=" && [:pick $ln 18 [:len $ln]] ~ "^[0-9]+\$") do={
                    :set footer [:tonum [:pick $ln 18 [:len $ln]]]
                  } else={
                    :local ok false
                    :if ($footer < 0 && $ln ~ $lineRe) do={
                      :local sl [:find $ln "/"]
                      :local ip $ln
                      :local plen $maxPlen
                      :if ([:typeof $sl] = "num") do={
                        :set ip [:pick $ln 0 $sl]
                        :set plen [:tonum [:pick $ln ($sl + 1) [:len $ln]]]
                      }
                      :if ($plen >= $minPlen && $plen <= $maxPlen) do={
                        :if ($v6) do={
                          :if ([:typeof [:toip6 $ip]] = "ip6") do={
                            :do {
                              /ipv6 firewall address-list add list=$target address=$ln timeout=7d
                              :set added ($added + 1)
                              :set ok true
                            } on-error={}
                          }
                        } else={
                          :if ([:typeof [:toip $ip]] = "ip") do={
                            :do {
                              /ip firewall address-list add list=$target address=$ln timeout=7d
                              :set added ($added + 1)
                              :set ok true
                            } on-error={}
                          }
                        }
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
        } on-error={ :set reason "read error" }
        :if ($reason = "") do={
          :if ($footer < 0) do={
            :set reason "no footer"
          } else={
            :if ($footer != $entries) do={
              :set reason "header/footer mismatch"
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
          :if ($v6) do={
            /ipv6 firewall address-list remove [find where list=$target]
          } else={
            /ip firewall address-list remove [find where list=$target]
          }
          :if (!$boot) do={ /file remove [find where name=$fname] }
          :log error ("MBL: $fname rejected ($reason), active " . $fl . "list kept")
          :error "MBL: abort"
        }
        :local n $added

        # ---- switch rules, then empty the old list
        :if ($v6) do={
          /ipv6 firewall raw set [find where comment="MBL: in"] src-address-list=$target
          /ipv6 firewall raw set [find where comment="MBL: out"] dst-address-list=$target
          /ipv6 firewall raw set [find where comment="MBL: router-out"] dst-address-list=$target
          /ipv6 firewall address-list remove [find where list=$old]
        } else={
          /ip firewall raw set [find where comment="MBL: in"] src-address-list=$target
          /ip firewall raw set [find where comment="MBL: out"] dst-address-list=$target
          /ip firewall raw set [find where comment="MBL: router-out"] dst-address-list=$target
          /ip firewall address-list remove [find where list=$old]
        }

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
              :log warning ("MBL: " . $fl . "not enough flash space for the boot copy ($free bytes free, need more than 2 x $fsize), keeping the previous $lastFile")
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
                :log warning ("MBL: " . $fl . "could not rename $tmpFile to $lastFile, boot will use $tmpFile")
              }
            } else={
              /file remove [find where name=$newFile]
              :log warning ("MBL: " . $fl . "could not save the boot copy, keeping the previous $lastFile")
            }
          }
        }

        :if (!$v6) do={ :set mblLastOk true }
        :log info ("MBL: loaded $n " . $fl . "entries into $target (list generated $gen)")

        # The notices below are IPv4 only: v2 never had IPv6 files, and the
        # IPv6 list comes from the same build as the IPv4 one.
        :if (!$v6) do={
          # ---- v2 leftovers: its boot copies are only removed now that a v3
          # load has succeeded, so an upgrade never loses the last good copy.
          # Errors are ignored: they must never turn a good load into "update aborted".
          :do {
            :local v2 [/file find where name~"^(flash/)?mbl-.*\\.rsc\$"]
            :if ([:len $v2] > 0) do={
              /file remove $v2
              :log info "MBL: removed v2 files"
            }
          } on-error={}

          # ---- stale list: the list is loaded either way; this only warns, e.g.
          # when the GitHub Action has stopped. Errors here are ignored so they can
          # never fail an update that already succeeded.
          :do {
            :if ($gen != "unknown") do={
              :local age ([$mblDays [/system clock get date]] - [$mblDays [:pick $gen 0 10]])
              :if ($age > $maxAgeDays) do={ :log warning "MBL: list is $age days old" }
            }
          } on-error={}

          # ---- newer script: only a notice, the router never updates itself.
          # mblVerGt rejects any value that is not MAJOR.MINOR.PATCH, so only such
          # a value is logged. Errors are ignored, as for the stale list warning.
          :do {
            :if ([$mblVerGt $pubScript $scriptVersion] = true) do={
              :log warning ("MBL: script $pubScript available (installed $scriptVersion) - reinstall: /tool fetch url=\"https://raw.githubusercontent.com/Psycomy/MikrotikBlockList/main/routeros/install.rsc\" check-certificate=yes; /import install.rsc")
            }
          } on-error={}
        }
      } on-error={ :log warning ("MBL: " . $fl . "update aborted") }
    }
  }
  :set mblRunning false
}
}

# Inject the settings into the stored script: replace placeholder $1 with $2.
:local mblInject do={
  :local src [/system script get [find where name="mbl-update"] source]
  :local p [:find $src $1]
  :if ([:typeof $p] = "nil") do={ :error "MBL: internal error, placeholder $1 not found in mbl-update" }
  /system script set [find where name="mbl-update"] \
    source=([:pick $src 0 $p] . $2 . [:pick $src ($p + [:len $1]) [:len $src]])
}
$mblInject "@MBL_URL@" $mblUrl
$mblInject "@MBL_URL6@" $mblUrl6
$mblInject "@MBL_VERSION@" $mblScriptVersion
$mblInject "@MBL_VARIANT@" $mblVar
$mblInject "@MBL_IPV6@" $mblV6

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
# Drop rules point at $active / $active6 (see step 3); mbl-update switches them later.
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
# The same 6 rules in /ipv6 firewall raw, with IPv6 on only.
:if ($mblV6 = "yes") do={
  :local existing6 [/ipv6 firewall raw find]
  :if ([:len $existing6] = 0) do={
    /ipv6 firewall raw add chain=prerouting src-address-list=mbl6-allow action=accept comment="MBL: allow-in"
    /ipv6 firewall raw add chain=prerouting dst-address-list=mbl6-allow action=accept comment="MBL: allow-out"
    /ipv6 firewall raw add chain=prerouting in-interface-list=WAN src-address-list=$active6 action=drop comment="MBL: in"
    /ipv6 firewall raw add chain=prerouting in-interface-list=LAN dst-address-list=$active6 action=drop log=yes log-prefix="MBL-OUT" comment="MBL: out"
    /ipv6 firewall raw add chain=output dst-address-list=mbl6-allow action=accept comment="MBL: allow-router-out"
    /ipv6 firewall raw add chain=output dst-address-list=$active6 action=drop comment="MBL: router-out"
  } else={
    :local anchor6 ($existing6->0)
    /ipv6 firewall raw add chain=prerouting src-address-list=mbl6-allow action=accept comment="MBL: allow-in" place-before=$anchor6
    /ipv6 firewall raw add chain=prerouting dst-address-list=mbl6-allow action=accept comment="MBL: allow-out" place-before=$anchor6
    /ipv6 firewall raw add chain=prerouting in-interface-list=WAN src-address-list=$active6 action=drop comment="MBL: in" place-before=$anchor6
    /ipv6 firewall raw add chain=prerouting in-interface-list=LAN dst-address-list=$active6 action=drop log=yes log-prefix="MBL-OUT" comment="MBL: out" place-before=$anchor6
    /ipv6 firewall raw add chain=output dst-address-list=mbl6-allow action=accept comment="MBL: allow-router-out" place-before=$anchor6
    /ipv6 firewall raw add chain=output dst-address-list=$active6 action=drop comment="MBL: router-out" place-before=$anchor6
  }
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
  :put "MBL: installed (script $mblScriptVersion, variant $mblVar, ipv6 $mblV6)"
  :log info "MBL: installed (script $mblScriptVersion, variant $mblVar, ipv6 $mblV6)"
} else={
  :put "MBL: WARNING installed (script $mblScriptVersion, variant $mblVar, ipv6 $mblV6), but the first load failed or was skipped. See /log print where message~\"MBL\""
  :log warning "MBL: installed (script $mblScriptVersion, variant $mblVar, ipv6 $mblV6), but the first load failed or was skipped"
}
}
