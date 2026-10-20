# Estudio de fuentes — 2026-10-20

Objetivo: elegir las mejores listas **gratuitas** de IPv4 maliciosas para un MikroTik doméstico, que **no se solapen**, con pocos falsos positivos y licencia compatible con la redistribución no comercial.

## Método

- **Candidatas:** 44 URLs (las 13 actuales, las 2 opcionales y 29 nuevas). Salen de directorios mantenidos ([Bert-JanP/Open-Source-Threat-Intel-Feeds](https://github.com/Bert-JanP/Open-Source-Threat-Intel-Feeds), [threatcluster.io](https://threatcluster.io/free-threat-intelligence-feeds), [FireHOL](https://iplists.firehol.org/)) y de búsqueda propia.
- **Normalización:** cada lista se descarga y se pasa por el mismo filtro que el generador (`mbl.normalize`: fuera bogons, CGNAT, rangos privados y redes más amplias que /8).
- **Métricas:**
  - Tamaño, en entradas tras agregar y en direcciones.
  - Frescura: cabecera *Last-Modified* o fecha interna.
  - Solapamiento: porcentaje de A contenido en B, medido por direcciones.
  - Aportación única frente al resto.
  - Aportación marginal: hosts nuevos que añade sobre un conjunto base (sin contar bloques mayores de /24).
- **Falsos positivos:**
  - Cruce con los rangos de Cloudflare, Fastly y CloudFront.
  - Cruce con las IPs de los **5.000 dominios más visitados** ([Tranco](https://tranco-list.eu/), con `www.` incluido): 9.172 IPs.
- **Licencia:** términos de cada fuente (cabecera o web).

Los scripts quedaron en el scratchpad de la sesión. Es una foto de un día: los tamaños cambian a diario.

## Hallazgos sobre el catálogo actual

| Fuente actual | Hallazgo | Acción |
|---|---|---|
| `feodo` (abuse.ch) | **Muerta**: última actualización el 2026-03-04 y solo 1 IP. | Quitar |
| `c2intel` | Está contenida al **100 % en ThreatFox**. | Quitar |
| `bruteforceblocker` | Es casi idéntica a `et-compromised` (98 % y 96 % en ambos sentidos) y no aporta nada nuevo. | Quitar |
| `et-block` | Es Spamhaus DROP + DShield (contiene el 100 % y el 95 %). Solo añade 1,7k hosts. | Quitar (se conservan sus dos fuentes primarias) |
| `stopforumspam` | Son rangos de **spam de foros** (/18 incluidos). Para un router no aportan protección y bloquear la salida hacia hosting es arriesgado. | Quitar |
| `spamhaus-drop` | Redes secuestradas. Cubre 14,8 millones de direcciones con solo 1.592 entradas. | **Mantener** (obligatoria) |
| `cins`, `blocklist-de-all` | Son las dos fuentes de atacantes que más aportan: +8,7k y +17k hosts únicos. | **Mantener** |
| `ipsum-3` | Agregador por consenso (IP vista en ≥3 listas). Añade 3,4k hosts sobre el resto. | **Mantener** |
| `dshield`, `et-compromised`, `binarydefense`, `threatfox-recent` | Pequeñas, con aportación única y sin falsos positivos. | **Mantener** |

En los 5.000 sitios más visitados, el catálogo actual solo coincide con `lookmovie2.to`, un sitio pirata alojado en un rango que Spamhaus marca como secuestrado. Ese caso es correcto.

## Candidatas nuevas

| Candidata | Entradas | Aporta (hosts nuevos) | Falsos positivos | Licencia | Veredicto |
|---|---:|---:|---|---|---|
| **Turris Sentinel greylist** (CZ.NIC, honeypots en routers Turris) | 9.9k | +5.1k | 161 IPs de Cloudflare WARP | CC BY-NC-SA 4.0 | **Añadir.** Atacantes vistos por routers domésticos reales. |
| **ThreatCluster** (IPs maliciosas, 30 días) | 163 | +146 | 0 | No indicada | **Añadir.** Pequeña y de alta confianza. |
| AbuseIPDB s100 7d (borestad) | 61k | +37k | 0 | No indicada ("con permiso" de AbuseIPDB) | Opcional, desactivada. Dobla la lista; licencia poco clara. |
| Dataplane (ssh, telnet, vnc, sip) | 0,1k–41k | hasta +46k | 0 | **Prohíbe redistribuir** | Descartar |
| Data-Shield | 84k | +69k | 0 | GPLv3 (agregador) | Descartar: agregador de otras listas y grande |
| ThreatHive | 165k | +150k | `doh.pub` | No indicada (agregador) | Descartar: enorme y bloquea un servidor DoH |
| blocklist.net.ua | 178k | +200k | **10 sitios top**, entre ellos la CDN bunny.net | — | Descartar |
| romainmarcoux malicious-outgoing | 35k | +27k | **13 sitios top** (8x8.com, edgecdn…) | — | Descartar |
| TweetFeed (mes) | 634 | +530 | **17 sitios top** | CC0 | Descartar: demasiados falsos positivos para bloquear la salida |
| FireHOL level1 | 4.6k | 0 útil | 0 | — | Descartar: Spamhaus + DShield + Feodo + bogons, ya cubiertos |
| FireHOL level2/level3 | 18k / 11k | +7k / +14k | level3 bloquea **dns.google** y **githubusercontent.com** | — | Descartar |
| ThreatView high-confidence | 15k | +7k | Entradas basura (`0.0.0.2`, `1.0.0.0`…) | — | Descartar por calidad |
| IPsum nivel 2 / nivel 4 | 25k / 8.6k | +14k / +2k | 0 | Unlicense | Nivel 3 sigue siendo el equilibrio; nivel 2 duplica el ruido |
| sblam | 1.1k | +1k | 4 IPs de Cloudflare | — | Descartar: spam de formularios HTTP, no aplica a un router |
| blocklist.de *strongips* | 272 | +7 | 0 | — | Descartar: subconjunto de `all` |
| Feodo completa, SSLBL agresiva | 5 / 0 | — | — | — | Muertas (2026-03 y 2025-01) |
| C2-Tracker (montysecurity) | — | — | — | — | Repositorio archivado (2026-04) |
| ThreatMon, Criminal IP C2, ELLIO, DigitalSide, CyberCure, darklist.de | 0–3 | — | — | — | Muertas, vacías, bajo JavaScript o caídas hoy |

## Propuesta

10 fuentes (antes 13):

- **Ataques entrantes:** `spamhaus-drop` (obligatoria), `dshield`, `et-compromised`, `cins`, `blocklist-de-all`, `ipsum-3`, `binarydefense` y la nueva **`turris-greylist`**.
- **C2 y salientes:** `threatfox-recent` y la nueva **`threatcluster`**.

| | Actual | Propuesta |
|---|---:|---:|
| Fuentes | 13 | 10 |
| Entradas | 34.220 | **39.321** (+15 %) |
| Sitios top-5000 bloqueados | 1 (correcto) | 1 (el mismo) |
| IPs de CDN bloqueadas | 13 | 174 (todas de Cloudflare) → **0** con el cambio de abajo |

Además, propongo **añadir los 15 rangos IPv4 de Cloudflare a `allowlist.txt`**. Turris y blocklist.de listan IPs de salida de Cloudflare WARP, y bloquear la salida hacia Cloudflare rompería webs legítimas. Bloquear la entrada desde esos rangos no aporta nada, porque son proxies compartidos.

Casi todo el aumento de entradas viene de Turris. Encaja de sobra en el tope de 2x y añade unos 1-2 MiB de RAM por lista.

## Limitaciones

- Es una medición de un solo día. No medí la estabilidad día a día ni la tasa real de aciertos contra tráfico propio.
- "Aportación única" no equivale a "calidad": una IP que solo lista una fuente puede ser un hallazgo o ruido. El cruce con sitios populares y con CDN solo detecta los falsos positivos más graves.
- Las licencias "no indicada" (ThreatCluster, AbuseIPDB vía borestad) no son un permiso explícito. Quedan anotadas en `NOTICE.md`, igual que blocklist.de.
