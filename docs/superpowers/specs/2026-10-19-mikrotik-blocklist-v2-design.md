# MikrotikBlockList v2 — Documento de diseño

Fecha: 2026-10-19 · Repo: `Psycomy/MikrotikBlockList` (GPL-3.0)

## 1. Intención

Usar el firewall de los routers MikroTik para protegerse con listas públicas de
IPs peligrosas, **bloqueando tanto el tráfico entrante desde ellas como el
saliente hacia ellas**. El proyecto nace para uso doméstico, pero debe valer
también en un entorno empresarial sin cambiar de enfoque. Es público y
compartido: cualquiera debe poder usarlo copiando un par de líneas en su router.

La v1 (2023) tenía la idea correcta, pero en la práctica no funcionaba:
- perdía los rangos CIDR;
- los nombres no coincidían entre el generador y el instalador;
- `install.rsc` tenía un error de sintaxis;
- un fallo de descarga dejaba la lista vacía;
- usaba fuentes muertas o que no eran listas de IPs.

La v2 es una reescritura sobre el mismo repo.

**Ámbito de uso: doméstico / no comercial.** Varias fuentes solo permiten
uso no comercial, así que el proyecto se declara **no apto para uso
empresarial**. El README lo dice de forma visible, junto con la licencia de
cada fuente. *(Decisión del usuario.)*

## 2. Objetivos

1. **Generación automática diaria en GitHub Actions**, sin servidor propio. La
   lista resultante se publica en el propio repo y los routers la descargan
   de la URL raw de GitHub.
2. **Datos limpios.** El resultado debe tener:
   - solo IPv4 y CIDR válidos, con su máscara conservada;
   - ningún rango privado, reservado, bogon, CGNAT (100.64.0.0/10), multicast ni loopback;
   - duplicados eliminados y rangos solapados agregados (`collapse_addresses`);
   - una allowlist versionada en el repo para excluir falsos positivos.
3. **Instalación en el router con un copia-pega**, que deje montado:
   - el script de actualización;
   - el scheduler;
   - las reglas de firewall.

   Debe ser idempotente: volver a ejecutarla actualiza la instalación sin
   duplicar nada. Además habrá un desinstalador.
4. **Bloqueo en ambas direcciones:**
   - **Entrante:** se descarta en `/ip firewall raw`, cadena `prerouting`, lo
     que tenga origen en la lista y entre por la WAN. Se hace antes del
     connection tracking, así que es barato.
   - **Saliente desde la LAN:** se descarta lo que vaya hacia la lista, con
     log y un prefijo identificable para detectar equipos infectados.
   - **Saliente desde el propio router:** se descarta en `raw`, cadena `output`.
5. **Actualización segura en el router:**
   - si la descarga o la validación fallan, se conserva la lista anterior;
   - nunca debe quedar vacía por un fallo;
   - el tiempo sin protección durante el reemplazo tiene que ser mínimo.
6. **Poco desgaste de la flash y protección tras reinicio.** Las entradas son
   dinámicas (con `timeout`), así que no se guardan en la configuración. El
   router guarda en flash la **última lista válida** (`mbl-last.rsc`), una
   escritura al día de pocos cientos de KB. En el arranque la importa
   enseguida, sin esperar a la red, y después intenta actualizarla. Así un
   reinicio sin Internet no deja el router desprotegido. *(Decisión mía, a raíz
   de la revisión.)*
7. **Seguridad de la cadena de suministro:**
   - la descarga va siempre por HTTPS con `check-certificate=yes`;
   - el `.rsc` publicado solo contiene comandos `add` a la address-list,
     generados por el propio código a partir de objetos `ipaddress` validados;
   - el script del router comprueba, antes de importarlo, que el fichero tiene
     el formato esperado (cabecera y marcador final).

## 3. No objetivos (por ahora)

- RouterOS v6. **Solo v7.**
- IPv6 (se puede añadir más adelante, pero no ahora).
- Uso empresarial o comercial, por las licencias de las fuentes.
- Bloqueo por dominios/DNS. Las listas tipo `hosts` quedan fuera.
- Panel web, servidor propio o fuentes de pago.
- Listas personalizadas por router, más allá de la allowlist local opcional (ver §6.4).

## 4. Anti-objetivos (fallaría aunque "funcione")

- **Cortarle el acceso al usuario.** Por ejemplo:
  - bloquear rangos privados o de CGNAT;
  - bloquear la IP de gestión;
  - meter reglas que dejen fuera Winbox o SSH desde la LAN.
- Que el router **ejecute código arbitrario** venido de Internet.
- Que un fallo de GitHub o de una fuente **vacíe la lista** o publique una lista
  anormalmente pequeña.
- **Ensuciar el historial de `main`** con un commit diario de datos.
- **Redistribuir fuentes cuya licencia prohíba la redistribución,** aunque
  sea con fines no comerciales. Se admiten fuentes "solo uso no comercial".

## 5. Restricciones

- RouterOS v7. El builder debe fijar y documentar la **versión mínima de v7**
  necesaria para lo que use, en particular el almacén de certificados
  integrado para HTTPS y `:onerror` si se usa.
- Ejecución en GitHub Actions (runner `ubuntu-latest`, gratis en repo público).
- El hardware es MikroTik "de verdad" (no un router doméstico convencional),
  pero la lista debe mantenerse razonablemente compacta, del orden de decenas
  de miles de entradas como mucho, para ir bien en equipos tipo hAP.

## 6. Cómo se hace (decidido)

### 6.1 Lenguaje y estructura

**Python 3.12 solo con biblioteca estándar** (`urllib.request`, `ipaddress`,
`tomllib`, `concurrent.futures`, `unittest`). No hay dependencias que instalar
y todo funciona tal cual en Actions. *(Decisión mía: el usuario dejó el
lenguaje a mi criterio.)*

Estructura propuesta (el builder puede ajustarla):

```
sources.toml          # catálogo de fuentes
allowlist.txt         # CIDR que nunca se bloquean
mbl/                  # paquete: fetch, parsers, normalización, salida
tests/                # unittest con fixtures de cada formato de fuente
routeros/
  install.rsc         # instalador idempotente
  uninstall.rsc
.github/workflows/build.yml
README.md
```

Se eliminan `Mikrotik.py` y el `install.rsc` antiguo de la raíz.

### 6.2 Catálogo de fuentes (`sources.toml`)

Cada fuente declara:
- `name`;
- `url`;
- `format`: `plain` (una IP o CIDR por línea, con comentarios `#`/`;`),
  `spamhaus` (CIDR con `; SBLxxx`), `dshield` (`inicio fin máscara`) o el
  que haga falta;
- `enabled`;
- `required`: si falla, la build falla;
- `license_note`.

Cada formato tiene su parser. Nada de regex genérica sobre el texto entero.

Cada fuente lleva además una `category`: `attack` (atacantes que entran) o
`c2` (servidores de mando y control a los que se sale). Las dos categorías
van a la misma address-list. La categoría sirve para las estadísticas y para
la tabla del README.

**Conjunto inicial** (todas verificadas vivas el 2026-10-19). El builder revisa
la licencia de cada una: descarta las que no permitan redistribuir y anota en
el README las que sean "solo uso no comercial".

| Fuente | Tipo |
|---|---|
| Spamhaus DROP (`drop.txt`, ya incluye EDROP) | redes secuestradas, required |
| abuse.ch Feodo Tracker (recommended) | C2 de botnets |
| Emerging Threats `compromised-ips.txt` | IPs comprometidas |
| Emerging Threats `emerging-Block-IPs.txt` | DShield + Spamhaus |
| CINS Army `ci-badguys.txt` | atacantes |
| blocklist.de `all.txt` | ataques (SSH, mail, web…) |
| GreenSnow | atacantes |
| BruteForceBlocker | fuerza bruta SSH |
| SANS ISC `block.txt` (formato dshield) | top atacantes |
| StopForumSpam `toxic_ip_cidr.txt` | rangos tóxicos |
| IPsum nivel 3 (stamparm, ~19k) | agregado con puntuación. Sustituye a los niveles 6-8 de la v1 |
| Binary Defense `banlist.txt` | atacantes (términos no comerciales) |
| **Nueva:** abuse.ch ThreatFox `export/csv/ip-port/recent/` (~3,5k, CC0) | C2/malware, `format=threatfox_csv` (extraer la IP de `ip:port`) |
| **Nueva:** drb-ra C2IntelFeeds `IPC2s-30day.csv` | C2 (Cobalt Strike, etc.) |

**Nuevas opcionales, desactivadas por defecto por tamaño** (`enabled=false`;
el usuario puede activarlas en un fork):
- Data-Shield IPv4 Blocklist (~89k).
- borestad AbuseIPDB `s100` (~128k en la ventana de 30 días). Si se
  activa, mejor una ventana más corta.

**Descartados los agregadores de agregadores**, como bitwire-it (4,6 M
entradas) o romainmarcoux. Duplican las fuentes primarias y disparan el
tamaño.

**Descartadas:**
- StevenBlack hosts: son dominios, no IPs.
- MaxMind: da 404.
- Talos: da 403.
- snort.org: devuelve HTML.
- Spamhaus EDROP: está vacía porque se fusionó con DROP.
- sslbl: no tiene IPs.
- AlienVault y azorult-tracker: llevan años sin mantenerse.
- Las URLs duplicadas.

FireHOL level1 queda **fuera**, porque su contenido ya está cubierto por
DROP/DShield/Feodo y mete bogons. Esto es decisión mía.

### 6.3 Generación y publicación

1. Descargar las fuentes en paralelo, con timeout, reintentos y un User-Agent
   honesto que identifique el proyecto.
2. Parsear y normalizar las entradas.
3. Filtrar con `ipaddress`: descartar `not is_global`, multicast, reservadas y
   cualquier CIDR más amplio que /8. Restar la allowlist.
4. Agregar las redes con `collapse_addresses`.
5. Ordenar el resultado de forma determinista.
6. **Comprobaciones de seguridad.** Si alguna falla, la build falla y no se
   publica nada, de modo que los routers siguen con la lista anterior:
   - una fuente `required` ha fallado;
   - el total de entradas está por debajo de un mínimo absoluto;
   - el total ha caído más de un X % frente a la publicación anterior
     (umbral configurable, por ejemplo 50 %).
7. Generar:
   - `blocklist.rsc`: cabecera con fecha, número de entradas y versión de
     formato; líneas `add`; marcador final `# MBL-END`;
   - `blocklist.txt`: CIDR en texto plano, útil para otros sistemas;
   - `stats.json`: entradas por fuente, total, fuentes caídas.
8. Publicar en una **rama huérfana `lists`**, sobrescrita en cada ejecución
   con un único commit (force-push), para no engordar el historial. La URL que
   usan los routers es
   `https://raw.githubusercontent.com/Psycomy/MikrotikBlockList/lists/blocklist.rsc`.
   *(Decisión mía.)*

**Workflow:**
- se ejecuta a diario (cron, por ejemplo a las 04:00 UTC), con
  `workflow_dispatch` para lanzarlo a mano y en cada push a `main`;
- en los push y en los PR se ejecutan los tests;
- solo publica desde `main`;
- un fallo del workflow lo notifica GitHub al dueño por correo.

### 6.4 Lado RouterOS v7

**Nombres.** Todo lo que crea el instalador lleva el prefijo `mbl`: la
address-list `mbl-blocklist`, los scripts `mbl-update`, los schedulers y los
comentarios `MBL:` en las reglas. Así se puede actualizar o desinstalar sin
tocar nada del usuario.

**Instalación** (lo que el usuario pega en el router):

```
/tool fetch url="https://raw.githubusercontent.com/Psycomy/MikrotikBlockList/main/routeros/install.rsc" check-certificate=yes; /import install.rsc
```

El instalador:
1. Comprueba la versión de RouterOS y que existen las interface-lists `WAN`
   y `LAN` (vienen en la configuración por defecto). Si no existen, para con
   un mensaje claro y no crea nada.
2. Habilita la validación de certificados HTTPS: almacén integrado de v7 o
   importación de la CA, según la versión mínima elegida.
3. Elimina cualquier elemento `mbl`/`MBL:` de una instalación anterior y crea:
   - el script `mbl-update`;
   - un scheduler diario (con una hora aleatoria para no golpear GitHub todos
     a la vez);
   - un scheduler `start-time=startup` con espera a que haya red.
4. Crea las reglas al principio de sus cadenas:
   - `raw prerouting`, `in-interface-list=WAN`, `src-address-list=mbl-blocklist` → `drop`.
   - `raw prerouting`, `in-interface-list=LAN`, `dst-address-list=mbl-blocklist`
     → `drop` con `log=yes` y `log-prefix="MBL-OUT"`. Si `raw` no admite el
     log que queremos, se usa `filter forward`, a criterio del builder.
   - `raw output`, `dst-address-list=mbl-blocklist` → `drop`.
5. Lanza la primera actualización.

**Script `mbl-update`:**
1. Descarga `blocklist.rsc` a un fichero temporal con
   `check-certificate=yes`.
2. Valida el fichero: existe, supera un tamaño mínimo y tiene la cabecera y
   el marcador `# MBL-END`. Si no, registra un error en el log y **sale sin
   tocar la lista actual**.
3. Reemplaza la lista con el mínimo tiempo sin protección. El mecanismo
   recomendado es:
   - importar a una lista provisional (`mbl-staging`);
   - comprobar que el número de entradas es razonable;
   - borrar las antiguas de `mbl-blocklist` y pasar las nuevas.

   El builder debe medir este mecanismo en un RouterOS v7 real o en CHR. Si
   encuentra uno mejor, lo usa y lo documenta.
4. Las entradas llevan un `timeout` (por ejemplo 7 días). Si las
   actualizaciones fallan durante una semana seguida, la lista caduca sola en
   vez de quedarse obsoleta para siempre.
5. Si todo va bien, renombra el fichero temporal a `mbl-last.rsc`, que pasa a
   ser la copia para el arranque. Si algo falla, borra el temporal y conserva
   la copia anterior. Escribe en el log un resumen: entradas
   cargadas y fecha de la lista.

**Allowlist local `mbl-allow`:** el instalador siempre la crea, junto con
reglas `accept` justo antes de las de bloqueo, en las dos direcciones. Sirve
para resolver un falso positivo en un router concreto sin tocar el repo.
Además, el instalador **añade automáticamente las IPs de origen públicas de
las sesiones activas** (`/user active`) con el comentario `MBL: admin`, para
que quien instala en remoto no se quede fuera si su IP aparece en alguna lista.
El README explica cómo añadir más IPs de gestión. *(Decisión mía, a raíz de
la revisión.)*

**Desinstalador:** borra todo lo que tenga prefijo `mbl`/`MBL:`.

### 6.5 Documentación

`README.md` **visualmente atractivo** *(petición del usuario)*. Debe tener:
- cabecera centrada con logo o banner (SVG propio en `docs/assets/`);
- badges: estado del workflow, fecha de la última lista, número de entradas
  y licencia;
- **aviso destacado** (`> [!WARNING]`) de "solo uso doméstico / no comercial";
- diagrama Mermaid del flujo: fuentes → Action → rama `lists` → router;
- instalación en un bloque de código copiable;
- tabla de fuentes con categoría y licencia;
- secciones plegables (`<details>`) para lo avanzado.

Los badges de fecha y entradas se generan con un endpoint de shields.io
leyendo un JSON de la rama `lists`.

Idioma: **inglés con sección en español** (al ser público, el inglés amplía
el alcance). Incluye:
- qué hace;
- instalación con una línea;
- qué reglas crea y por qué;
- cómo ver los bloqueos salientes (`/log print where message~"MBL-OUT"`);
- allowlist local;
- desinstalación;
- fuentes y sus licencias;
- versión mínima de RouterOS.

*(Decisión mía: el usuario puede preferir solo español.)*

## 7. Pruebas

- **Tests unitarios (`unittest`):**
  - cada parser con fixtures reales recortados;
  - filtrado de bogons y CGNAT;
  - allowlist;
  - agregación de redes;
  - comprobaciones de seguridad;
  - la salida `.rsc` solo contiene líneas `add` válidas y el marcador final.
- **Validación en RouterOS:** el instalador, la actualización, la
  reinstalación y la desinstalación se prueban en un **CHR v7 en el Proxmox
  del usuario** antes de anunciar la v2. El builder da las instrucciones para
  crear la VM. El usuario la crea y da acceso SSH por clave desde esta
  máquina, y las pruebas se lanzan por SSH. Es una VM de pruebas, así que
  admite pruebas que corten tráfico. Cubre tres escenarios:
  - fichero corrupto o truncado;
  - URL caída;
  - reinicio del router.

## 7b. Publicación

El usuario autoriza:
- hacer push a `main` de `Psycomy/MikrotikBlockList`;
- crear la rama `lists`;
- dar permisos de escritura a Actions (`gh` ya está autenticado como `Psycomy`).

Se hace al final, con los tests en verde y la validación en CHR superada.
Antes de cada paso irreversible se avisa en el chat.

## 8. Lo que queda a criterio del builder

- La estructura interna exacta del paquete `mbl`.
- Los umbrales concretos (mínimo absoluto, % de caída, `timeout`, prefijo
  máximo). El tamaño de "decenas de miles" es orientativo. Se añade un
  **máximo duro** configurable, por ejemplo 150.000 entradas tras agregar: si
  se supera, la build falla y hay que podar fuentes en `sources.toml`. No se
  recorta automáticamente. *(Decisión mía.)*
- La hora del cron.
- El mecanismo exacto de reemplazo en el router, siempre que cumpla el §6.4.
- Si el log saliente se hace en `raw` o en `filter`.
- La versión mínima de v7, con la condición de que quede documentada.
