# MikrotikBlockList v2 - RouterOS v7 uninstaller
# https://github.com/Psycomy/MikrotikBlockList
#
# Usage:
#   /tool fetch url="https://raw.githubusercontent.com/Psycomy/MikrotikBlockList/main/routeros/uninstall.rsc" check-certificate=yes; /import uninstall.rsc
#
# Removes only what install.rsc created (names mbl-* / comments MBL:*).
# Entries you added yourself to mbl-allow are kept.
# The built-in CA store setting is left as is: the "fetch" component that
# install.rsc may have added to /certificate settings builtin-trust-store is
# NOT removed. Set it back by hand to your previous value if you want.
{
/system scheduler remove [find where name~"^mbl-"]
/system script remove [find where name~"^mbl-"]
/ip firewall raw remove [find where comment~"^MBL:"]
/ip firewall address-list remove [find where list="mbl-a"]
/ip firewall address-list remove [find where list="mbl-b"]
/ip firewall address-list remove [find where list="mbl-allow" and comment="MBL: admin"]
# mbl files: RAM root (download) and flash/ (boot copy) on devices that have it
/file remove [find where name~"^(flash/)?mbl-.*\\.rsc\$"]
/system script environment remove [find where name~"^mbl"]
/file remove [find where name="uninstall.rsc" or name="flash/uninstall.rsc"]
:log info "MBL: uninstalled"
}
