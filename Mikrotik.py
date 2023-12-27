import re
import requests
from datetime import datetime

def current_date_format(date):
    months = ("Enero", "Febrero", "Marzo", "Abri", "Mayo", "Junio", "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre")
    day = date.day
    month = months[date.month - 1]
    year = date.year
    messsage = "{} de {} del {}".format(day, month, year)

    return messsage

now = datetime.now()

def obtener_ips(url):
    try:
        cabecera = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:91.0) Gecko/20100101 Firefox/91.0"}
        response = requests.get(url, headers=cabecera)
        response.raise_for_status()
        datos = response.text
        ips = re.findall(r'\b(?:\d{1,3}\.){3}\d{1,3}\b', datos)
        return ips
    except requests.exceptions.RequestException as e:
        print("Error de conexión:", e)
        return []

def generar_archivo_rsc(ips):
    with open("ipBlock.rsc", "w") as archivo:
        archivo.write("# Generado el " + current_date_format(now) + "\n")
        archivo.write("/ip firewall address-list\n")
        #archivo.write("remove [find list=ipBlock]\n")  # Eliminar direcciones IP anteriores
        for ip in ips:
            archivo.write(f"add list=ipBlock address={ip}\n")
    print("Archivo rsc generado correctamente.")

def main():
    lista_servidores = [
        "https://feodotracker.abuse.ch/downloads/ipblocklist_recommended.txt",
        "https://reputation.alienvault.com/reputation.generic",
        "https://sslbl.abuse.ch/blacklist/sslipblacklist.txt",
        "https://azorult-tracker.net/api/list/ip?format=plain",
        "https://www.binarydefense.com/banlist.txt",
        "https://botscout.com/last_caught_cache.txt",
        "http://cinsscore.com/list/ci-badguys.txt",
        "http://cinsarmy.com/list/ci-badguys.txt",
        "http://danger.rulez.sk/projects/bruteforceblocker/blist.php",
        "https://rules.emergingthreats.net/fwrules/emerging-Block-IPs.txt",
        "https://rules.emergingthreats.net/blockrules/compromised-ips.txt",
        "https://rules.emergingthreats.net/open/suricata/rules/compromised-ips.txt",
        "http://lists.blocklist.de/lists/all.txt",
        "http://blocklist.greensnow.co/greensnow.txt",
        "https://isc.sans.edu/block.txt",
        "https://www.spamhaus.org/drop/drop.txt",
        "https://www.spamhaus.org/drop/edrop.txt",
        "https://www.maxmind.com/en/high-risk-ip-sample-list",
        "https://www.stopforumspam.com/downloads/toxic_ip_cidr.txt",
        "http://rules.emergingthreats.net/open/suricata/rules/compromised-ips.txt",
        "https://raw.githubusercontent.com/ktsaou/blocklist-ipsets/master/firehol_level1.netset",
        "https://www.spamhaus.org/drop/drop.txt",
        "https://www.spamhaus.org/drop/edrop.txt",
        "https://snort.org/downloads/ip-block-list",
        "https://raw.githubusercontent.com/stamparm/ipsum/master/levels/6.txt",
        "https://raw.githubusercontent.com/stamparm/ipsum/master/levels/7.txt",
        "https://raw.githubusercontent.com/stamparm/ipsum/master/levels/8.txt",
        "http://talosintelligence.com/documents/ip-blacklist",
        "https://raw.githubusercontent.com/StevenBlack/hosts/master/alternates/fakenews-gambling-porn-social/hosts"
    ]

    lista_ips = []
    for servidor in lista_servidores:
        ips = obtener_ips(servidor)
        lista_ips.extend(ips)

    ips_unicas = list(set(lista_ips))

    with open("ipBlock.txt", "w") as archivo:
        archivo.write("\n".join(ips_unicas))

    generar_archivo_rsc(ips_unicas)
    print("Se obtuvieron", len(ips_unicas), "IPs únicas.")

if __name__ == '__main__':
    main()

