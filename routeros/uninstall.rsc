# MikroBlockList v3 - RouterOS v7 uninstaller
# https://github.com/Psycomy/MikroBlockList
#
# Usage:
#   /tool fetch url="https://raw.githubusercontent.com/Psycomy/MikroBlockList/main/routeros/uninstall.rsc" check-certificate=yes; /import uninstall.rsc
#
# Removes only what install.rsc created (names mbl-* / comments MBL:* and
# MBL-OLD:*, the old rules an interrupted reinstall may leave).
# Both families (IPv4 and IPv6). Entries you added yourself to mbl-allow
# or mbl6-allow are kept.
# The built-in CA store setting is left as is: the "fetch" component that
# install.rsc may have added to /certificate settings builtin-trust-store is
# NOT removed. Set it back by hand to your previous value if you want.
{
/system scheduler remove [find where name~"^mbl-"]
/system script remove [find where name~"^mbl-"]
/ip firewall raw remove [find where comment~"^MBL(-OLD)?:"]
/ip firewall address-list remove [find where list="mbl-a"]
/ip firewall address-list remove [find where list="mbl-b"]
/ip firewall address-list remove [find where list="mbl-allow" and comment="MBL: admin"]
/ipv6 firewall raw remove [find where comment~"^MBL(-OLD)?:"]
/ipv6 firewall address-list remove [find where list="mbl6-a"]
/ipv6 firewall address-list remove [find where list="mbl6-b"]
/ipv6 firewall address-list remove [find where list="mbl6-allow" and comment="MBL: admin"]
# mbl / mbl6 files: RAM root (download) and flash/ (boot copy) on devices that have it
/file remove [find where name~"^(flash/)?mbl6?-.*\\.(rsc|txt)\$"]
/system script environment remove [find where name~"^mbl"]
/file remove [find where name="uninstall.rsc" or name="flash/uninstall.rsc"]
:log info "MBL: uninstalled"
}
