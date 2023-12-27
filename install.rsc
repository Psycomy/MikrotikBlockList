# A firewall rule must be added:
# /ip firewall filter add chain=input action=drop connection-state=new src-address-list=wiberBlock in-interface=ether1
# Note: Replace the "IFNAME" at the end in: in-interface with the one you have configured (ether1,ether2...).
/system script 
add name="descarga-ipsmaliciosas" source={/tool fetch url="https://FILEURL/ipsbloqueo.rsc" mode=https}
add name="reemplazo-ipsmaliciosas" source {/ip firewall address-list remove [find where list="wiberBlock"]; /import file-name=ipsbloqueo.rsc; /file remove ipsbloqueo.rsc}
/system scheduler 
add interval=7d name="descargaips" start-date=Jan/01/2000 start-time=00:05:00 on-event=descarga-ipsmaliciosas
add interval=7d name="reemplazaips" start-date=Jan/01/2000 start-time=00:10:00 on-event=reemplazo-ipsmaliciosas
/file remove install.rsc
