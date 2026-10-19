# MikrotikBlockList v2 - RouterOS v7 uninstaller
# https://github.com/Psycomy/MikrotikBlockList
#
# Usage:
#   /tool fetch url="https://raw.githubusercontent.com/Psycomy/MikrotikBlockList/main/routeros/uninstall.rsc" check-certificate=yes; /import uninstall.rsc
#
# Removes only what install.rsc created (names mbl-* / comments MBL:*).
# Entries you added yourself to mbl-allow are kept.
# The built-in CA store setting is left as is.
{
/system scheduler remove [find where name~"^mbl-"]
/system script remove [find where name~"^mbl-"]
/ip firewall raw remove [find where comment~"^MBL:"]
/ip firewall address-list remove [find where list="mbl-a"]
/ip firewall address-list remove [find where list="mbl-b"]
/ip firewall address-list remove [find where list="mbl-allow" and comment="MBL: admin"]
/file remove [find where name~"^mbl-.*\\.rsc\$"]
/system script environment remove [find where name~"^mbl"]
:log info "MBL: uninstalled"
}
