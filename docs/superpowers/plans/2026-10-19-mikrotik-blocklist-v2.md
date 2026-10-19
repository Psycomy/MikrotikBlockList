# MikrotikBlockList v2 — Plan de implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Objetivo:** reescribir MikrotikBlockList para que:
- una GitHub Action genere a diario una lista limpia de IPs maliciosas;
- la publique en la rama `lists`;
- un instalador RouterOS v7 bloquee el tráfico entrante y el saliente con esa lista.

**Arquitectura:**
- **Generador:** un paquete Python (`mbl/`), solo con la biblioteca estándar. Lee `sources.toml`, descarga las fuentes, aplica a cada formato su parser, normaliza las redes con `ipaddress` y genera tres ficheros: `.rsc`, `.txt` y JSON. Antes de publicar pasa unas comprobaciones de seguridad.
- **Router:** usa **dos address-lists que se alternan** (`mbl-a` y `mbl-b`). La lista nueva se importa en la inactiva y, cuando está validada, se cambian las reglas para que apunten a ella. El cambio es atómico, sin ventana de desprotección. Después se borra la lista antigua.
- **Arranque:** la última lista válida se guarda en flash (`mbl-last.rsc`) y se importa al arrancar.

**Tecnología:** Python 3.12 (`urllib`, `ipaddress`, `tomllib`, `concurrent.futures`, `unittest`), GitHub Actions y scripting de RouterOS v7.

**Spec:** `docs/superpowers/specs/2026-10-19-mikrotik-blocklist-v2-design.md`

## Restricciones globales

- RouterOS **solo v7**. Versión mínima: se fija en la Tarea 9 tras probar en CHR, y queda en el README.
- Python 3.12, **sin dependencias externas**. Los tests usan `python -m unittest`.
- Solo IPv4.
- Prefijo `mbl`/`MBL:` en todo lo que se crea en el router. Address-lists:
  - `mbl-a` y `mbl-b`, que se alternan;
  - `mbl-allow`, la allowlist local.
- Valores fijos:

  | Parámetro | Valor |
  |---|---|
  | `MIN_TOTAL` | 5000 |
  | `MAX_TOTAL` | 150000 |
  | `MAX_DROP` | 0.5 |
  | Redes más amplias que /8 | se descartan |
  | Timeout de las entradas | `7d` |
  | Timeout de descarga | 30 s |
  | Reintentos | 2 |
  | Cron | `17 4 * * *` |
  | Tamaño mínimo del `.rsc` en el router | 100000 bytes |
  | Mínimo de entradas en el router | 1000 |

- User-Agent: `MikrotikBlockList/2.0 (+https://github.com/Psycomy/MikrotikBlockList)`.
- URL de la lista: `https://raw.githubusercontent.com/Psycomy/MikrotikBlockList/lists/blocklist.rsc`.
- Ámbito **doméstico / no comercial**. El aviso aparece en el README y en la cabecera del `.rsc`.
- El historial de `main` no recibe commits de datos. La rama `lists` es huérfana y se sobrescribe con un único commit.
- Toda la descarga en el router usa HTTPS con `check-certificate=yes`.

## Puntos de revisión

1. **Una fuente responde 200 con HTML** (por ejemplo, una página de Cloudflare) **o vacía.** Se trata como fuente fallida (0 entradas válidas) y no como "lista vacía válida". Lo cubre la Tarea 4: `test_zero_valid_entries_is_failure`.
2. **Entradas raras:** CRLF, BOM, espacios, host bits (`1.2.3.4/24`), ceros a la izquierda (`010.1.1.1`) o comentarios en mitad de la línea. Se normalizan o se descartan sin romper nada. Lo cubre la Tarea 2: `test_plain_edge_cases`.
3. **Una fuente mete `0.0.0.0/0` o un /4.** No debe llegar nunca a la salida. Lo cubre la Tarea 3: `test_drops_wider_than_slash8`.
4. **Se solapan dos actualizaciones** (la del arranque y la diaria). Un lock global impide que se ejecuten a la vez. Lo cubre la Tarea 9, caso CHR "ejecución concurrente".
5. **El router arranca sin NTP o sin red** y falla el certificado o el DNS. Aun así carga `mbl-last.rsc` y deja todo protegido. Lo cubre la Tarea 9, caso CHR "arranque sin red".

---

### Tarea 1: Esqueleto del proyecto y catálogo de fuentes

**Ficheros:**
- Borrar: `Mikrotik.py`, `install.rsc`
- Crear: `mbl/__init__.py`, `mbl/sources.py`, `sources.toml`, `allowlist.txt`, `.gitignore` (con `dist/` y `__pycache__/`)
- Test: `tests/__init__.py`, `tests/test_sources.py`

**Interfaces:**
- Produce `@dataclass(frozen=True) Source`, con estos campos:
  - `name: str`, `url: str`;
  - `format: str`: `plain`, `dshield`, `threatfox_csv` o `c2intel_csv`;
  - `category: str`: `attack` o `c2`;
  - `enabled: bool = True`, `required: bool = False`;
  - `license_note: str = ""`.
- Produce `load_sources(path: Path) -> list[Source]`. Devuelve solo las fuentes `enabled` y lanza `ValueError` si hay un formato o una categoría desconocidos o un `name` duplicado.
- Produce `load_allowlist(path: Path) -> list[IPv4Network]`. Ignora `#` y las líneas vacías.

- [ ] **Paso 1:** crear la rama de trabajo `git switch -c v2` y configurar la identidad local: `git config user.name Psycomy` y `git config user.email andatovid@gmail.com`.
- [ ] **Paso 2: test que falla.** `tests/test_sources.py`:
  - `test_loads_enabled_only`: un TOML temporal con 2 fuentes, una con `enabled=false`, devuelve 1;
  - `test_rejects_unknown_format`: lanza `ValueError`;
  - `test_rejects_duplicate_name`: lanza `ValueError`;
  - `test_repo_catalog_is_valid`: `load_sources(Path("sources.toml"))` no lanza nada, devuelve ≥ 10 fuentes y `spamhaus-drop` es `required`;
  - `test_allowlist_parses`: `"# x\n1.1.1.1\n8.8.8.0/24\n"` da `[1.1.1.1/32, 8.8.8.0/24]`.
- [ ] **Paso 3:** ejecutar `python -m unittest tests.test_sources -v`. Esperado: FAIL (ImportError).
- [ ] **Paso 4:** implementar `mbl/sources.py` con `tomllib`. Escribir `sources.toml` como array `[[source]]` con las fuentes del §6.2 del spec: las 13 activas y las 2 opcionales con `enabled=false`.

  | name | URL | format / category |
  |---|---|---|
  | `spamhaus-drop` | `https://www.spamhaus.org/drop/drop.txt` | plain/attack, required |
  | `feodo` | `https://feodotracker.abuse.ch/downloads/ipblocklist_recommended.txt` | plain/c2 |
  | `et-compromised` | `https://rules.emergingthreats.net/blockrules/compromised-ips.txt` | plain/attack |
  | `et-block` | `https://rules.emergingthreats.net/fwrules/emerging-Block-IPs.txt` | plain/attack |
  | `cins` | `https://cinsscore.com/list/ci-badguys.txt` | plain/attack |
  | `blocklist-de` | `https://lists.blocklist.de/lists/all.txt` | plain/attack |
  | `greensnow` | `https://blocklist.greensnow.co/greensnow.txt` | plain/attack |
  | `bruteforceblocker` | `https://danger.rulez.sk/projects/bruteforceblocker/blist.php` | plain/attack |
  | `dshield` | `https://www.dshield.org/block.txt` | dshield/attack |
  | `stopforumspam` | `https://www.stopforumspam.com/downloads/toxic_ip_cidr.txt` | plain/attack |
  | `ipsum-3` | `https://raw.githubusercontent.com/stamparm/ipsum/master/levels/3.txt` | plain/attack |
  | `binarydefense` | `https://www.binarydefense.com/banlist.txt` | plain/attack |
  | `threatfox` | `https://threatfox.abuse.ch/export/csv/ip-port/recent/` | threatfox_csv/c2 |
  | `c2intel` | `https://raw.githubusercontent.com/drb-ra/C2IntelFeeds/master/feeds/IPC2s-30day.csv` | c2intel_csv/c2 |
  | `datashield` | `https://raw.githubusercontent.com/duggytuxy/Data-Shield_IPv4_Blocklist/main/prod_data-shield_ipv4_blocklist.txt` | plain/attack, enabled=false |
  | `abuseipdb-s100` | `https://raw.githubusercontent.com/borestad/blocklist-abuseipdb/main/abuseipdb-s100-7d.ipv4` | plain/attack, enabled=false |

  Antes de escribirlo, comprobar con `curl -sI` que `abuseipdb-s100-7d.ipv4` existe. Si no, usar la ventana existente más corta.

  El `license_note` de cada fuente se rellena consultando sus términos en la web. Las que no permitan redistribuir se quitan del catálogo, y se anota el motivo en un comentario TOML.
- [ ] **Paso 5:** volver a ejecutar los tests. Esperado: PASS.
- [ ] **Paso 6:** commit: `feat: project skeleton and source catalog`. Incluye el borrado de `Mikrotik.py` y del `install.rsc` antiguo, y también `docs/superpowers/` (spec y plan).

### Tarea 2: Parsers por formato

**Ficheros:**
- Crear: `mbl/parsers.py`
- Test: `tests/test_parsers.py`, `tests/fixtures/` (un recorte real de unas 10 líneas por formato: `plain_spamhaus.txt`, `plain_ipsum.txt`, `dshield.txt`, `threatfox.csv`, `c2intel.csv`)

**Interfaces:**
- Produce `parse(fmt: str, text: str) -> ParseResult`.
- `ParseResult` es una dataclass con `networks: list[IPv4Network]` y `invalid: int`.
- Las redes se crean con `strict=False`, así que `1.2.3.4/24` pasa a `1.2.3.0/24`. Las entradas IPv6 se ignoran sin contarlas como inválidas.

**Reglas por formato:**
- **`plain`:** cada línea es un token IP o CIDR antes de cualquier `#`, `;` o espacio. Las líneas vacías o de comentario se ignoran.
- **`dshield`:** se ignoran las líneas `#` y la cabecera `Start`. Las columnas 1 y 3 (inicio y máscara) dan `inicio/máscara`.
- **`threatfox_csv`:** se ignoran las líneas `#`. Columna `ioc_value` entre comillas: `"1.2.3.4:443"` → `1.2.3.4/32`.
- **`c2intel_csv`:** se ignoran la cabecera y las líneas `#`. La primera columna es la IP.

- [ ] **Paso 1: test que falla.**
  - `test_plain_spamhaus`: el fixture da la lista de CIDR esperada con su máscara. Por ejemplo, `"1.10.16.0/20 ; SBL256894"` da `1.10.16.0/20`.
  - `test_plain_edge_cases`: la entrada `"﻿1.1.1.1\r\n  2.2.2.2  \n1.2.3.4/24\n010.1.1.1\nfoo\n3.3.3.3 # c\n::1\n"` da las redes `[1.1.1.1/32, 2.2.2.2/32, 1.2.3.0/24, 3.3.3.3/32]` e `invalid == 2`.
  - `test_dshield`: la línea `"64.62.156.0\t64.62.156.255\t24\t345\tHURRICANE"` da `64.62.156.0/24`.
  - `test_threatfox_csv`: el fixture da IPs `/32` sin puerto.
  - `test_c2intel_csv`: el fixture da IPs `/32` y la cabecera no se cuenta como inválida.
  - `test_html_page_yields_nothing`: `"<html><body>Just a moment...</body></html>"` da `networks == []`.
  - `test_unknown_format`: lanza `ValueError`.
- [ ] **Paso 2:** ejecutar `python -m unittest tests.test_parsers -v`. Esperado: FAIL.
- [ ] **Paso 3:** implementar `mbl/parsers.py`. Los fixtures se obtienen recortando con `curl … | head` las URLs reales de la Tarea 1.
- [ ] **Paso 4:** volver a ejecutar los tests. Esperado: PASS.
- [ ] **Paso 5:** commit: `feat: per-format source parsers`.

### Tarea 3: Normalización

**Ficheros:**
- Crear: `mbl/normalize.py`
- Test: `tests/test_normalize.py`

**Interfaces:**
- Produce `normalize(networks: Iterable[IPv4Network], allowlist: Iterable[IPv4Network], min_prefixlen: int = 8) -> list[IPv4Network]`. El orden de operaciones es:
  1. descartar `prefixlen < min_prefixlen`;
  2. descartar las redes que no sean `is_global`, o que sean `is_multicast` o `is_reserved`;
  3. restar la allowlist con `address_exclude`;
  4. aplicar `collapse_addresses`;
  5. ordenar.

  Se descarta en el paso 2 cualquier red que solape un rango no global, no solo las que estén contenidas en él. Por ejemplo, `100.0.0.0/8` contiene el CGNAT y se descarta entera.

- [ ] **Paso 1: test que falla.**
  - `test_drops_private_cgnat_bogons`: `10.0.0.0/8`, `192.168.1.0/24`, `100.64.0.0/10`, `127.0.0.1/32`, `0.0.0.0/8`, `224.0.0.0/3`, `169.254.0.0/16`, `172.16.0.0/12` y `198.18.0.0/15` dan `[]`.
  - `test_drops_wider_than_slash8`: `0.0.0.0/0`, `16.0.0.0/4` y `8.0.0.0/7` dan `[]`, y `8.0.0.0/8` se conserva.
  - `test_drops_overlapping_non_global`: `100.0.0.0/8` da `[]`.
  - `test_allowlist_excludes`: `1.1.1.0/24` con allowlist `1.1.1.1/32` da 8 redes que no contienen `1.1.1.1`, y la suma de sus direcciones es 255.
  - `test_collapse_and_sort`: `5.5.5.1/32`, `1.2.3.0/25`, `1.2.3.128/25` y `5.5.5.1/32` dan `[1.2.3.0/24, 5.5.5.1/32]`.
  - `test_deterministic`: dos llamadas con la entrada barajada dan el mismo resultado.
- [ ] **Paso 2:** ejecutar `python -m unittest tests.test_normalize -v`. Esperado: FAIL.
- [ ] **Paso 3:** implementar `mbl/normalize.py`.
- [ ] **Paso 4:** volver a ejecutar los tests. Esperado: PASS.
- [ ] **Paso 5:** commit: `feat: network normalization`.

### Tarea 4: Descarga de fuentes

**Ficheros:**
- Crear: `mbl/fetch.py`
- Test: `tests/test_fetch.py`

**Interfaces:**
- Consume `Source` (Tarea 1) y `parse` (Tarea 2).
- Produce `@dataclass SourceResult`, con estos campos:
  - `source: Source`;
  - `networks: list[IPv4Network]`;
  - `invalid: int`;
  - `error: str | None`.
- Produce `fetch_all(sources: list[Source], timeout: float = 30, retries: int = 2) -> list[SourceResult]`. Descarga en paralelo con `ThreadPoolExecutor(max_workers=8)` y devuelve los resultados en el orden de entrada.
- Una fuente con error HTTP, timeout o **0 redes válidas** queda con `error` relleno y `networks == []`.
- Se envía el User-Agent de las restricciones globales.

- [ ] **Paso 1: test que falla.** Los tests levantan un `http.server` local en un hilo y en un puerto libre:
  - `test_fetch_ok`: el servidor sirve `"1.1.1.1\n"` y el resultado tiene 1 red y `error is None`;
  - `test_http_error`: un 404 deja `error` relleno;
  - `test_zero_valid_entries_is_failure`: una respuesta HTML deja `error` con el texto `"no valid entries"`;
  - `test_retries_then_succeeds`: el servidor falla una vez con 500 y luego devuelve 200, y el resultado es OK;
  - `test_sends_user_agent`: el servidor registra la cabecera y coincide con la constante.
- [ ] **Paso 2:** ejecutar `python -m unittest tests.test_fetch -v`. Esperado: FAIL.
- [ ] **Paso 3:** implementar `mbl/fetch.py` con `urllib.request`. La espera entre reintentos es de 2 s, reducible en los tests mediante un parámetro `backoff: float = 2`.
- [ ] **Paso 4:** volver a ejecutar los tests. Esperado: PASS.
- [ ] **Paso 5:** commit: `feat: parallel source fetching`.

### Tarea 5: Comprobaciones de seguridad y salida

**Ficheros:**
- Crear: `mbl/checks.py`, `mbl/render.py`
- Test: `tests/test_checks.py`, `tests/test_render.py`

**Interfaces:**
- Produce `safety_errors(total: int, previous_total: int | None, failed_required: list[str], min_total=5000, max_total=150000, max_drop=0.5) -> list[str]`. Devuelve una lista vacía si todo está bien.
- Produce `write_outputs(out_dir: Path, networks: list[IPv4Network], results: list[SourceResult], generated_at: datetime) -> None`, que escribe estos ficheros:

  | Fichero | Contenido |
  |---|---|
  | `blocklist.rsc` | formato exacto descrito abajo |
  | `blocklist.txt` | un CIDR por línea; los `/32` sin máscara |
  | `stats.json` | `{"generated_at": ISO8601Z, "total": int, "sources": {name: {"category", "entries", "invalid", "error"}}}` |
  | `badge-entries.json` | `{"schemaVersion":1,"label":"entries","message":"<total con separador de miles>","color":"blue"}` |
  | `badge-updated.json` | `{"schemaVersion":1,"label":"updated","message":"YYYY-MM-DD","color":"brightgreen"}` |

**Formato exacto de `blocklist.rsc`:**

```
# MikrotikBlockList v2 - https://github.com/Psycomy/MikrotikBlockList
# For home / non-commercial use only (see source licenses in README)
# generated: 2026-10-19T04:17:00Z entries: 61234
:global mblTarget
/ip firewall address-list
add list=$mblTarget timeout=7d address=1.10.16.0/20
...
:global mblImportOk true
# MBL-END
```

- [ ] **Paso 1: tests que fallan.**
  - **Checks:**
    - `test_ok`: `safety_errors(60000, 58000, [])` da `[]`;
    - `test_required_failed`: un error que menciona `spamhaus-drop`;
    - `test_below_min`: con 4999 da 1 error;
    - `test_above_max`: con 150001 da 1 error;
    - `test_big_drop`: con `(20000, 60000, [])` da 1 error;
    - `test_first_run_no_previous`: con `(60000, None, [])` da `[]`.
  - **Render:**
    - `test_rsc_structure`: la primera línea empieza por `# MikrotikBlockList v2`. Las dos últimas son `:global mblImportOk true` y `# MBL-END`. Todas las líneas entre `/ip firewall address-list` y `:global mblImportOk` cumplen `^add list=\$mblTarget timeout=7d address=\d+\.\d+\.\d+\.\d+(/\d+)?$`.
    - `test_rsc_contains_only_expected_commands`: fuera de las líneas `add`, solo aparecen las líneas fijas de cabecera y pie.
    - `test_stats_and_badges`: los JSON son válidos, `total` coincide y `message` da `"61,234"` para 61234.
- [ ] **Paso 2:** ejecutar `python -m unittest tests.test_checks tests.test_render -v`. Esperado: FAIL.
- [ ] **Paso 3:** implementar `mbl/checks.py` y `mbl/render.py`.
- [ ] **Paso 4:** volver a ejecutar los tests. Esperado: PASS.
- [ ] **Paso 5:** commit: `feat: safety checks and output rendering`.

### Tarea 6: CLI de build

**Ficheros:**
- Crear: `mbl/__main__.py`, `mbl/build.py`
- Test: `tests/test_build.py`

**Interfaces:**
- Consume todo lo anterior.
- Produce `build(sources_path: Path, allowlist_path: Path, out_dir: Path, previous_stats_url: str | None, now: datetime | None = None, fetcher=fetch_all) -> int`. Devuelve un código de salida:
  - **0:** ha escrito las salidas;
  - **1:** han fallado las comprobaciones de seguridad y no ha escrito nada;
  - **2:** error de configuración.

  `previous_stats_url` se descarga para leer el `total` anterior. Si da 404 o falla la red, se toma `None` y se avisa en stderr.

  Por stdout imprime una tabla resumen por fuente. Si existe la variable `GITHUB_STEP_SUMMARY`, añade además la misma tabla en Markdown a ese fichero.
- CLI: `python -m mbl build --sources sources.toml --allowlist allowlist.txt --out dist --previous-stats <url>`.

- [ ] **Paso 1: test que falla.** Se usa un `fetcher` falso que devuelve `SourceResult` fijos:
  - `test_build_writes_outputs`: devuelve 0 y existen los 5 ficheros;
  - `test_build_refuses_on_required_failure`: devuelve 1 y `out_dir` no contiene `blocklist.rsc`;
  - `test_build_skips_drop_check_without_previous`: con `previous_stats_url=None` devuelve 0.
- [ ] **Paso 2:** ejecutar `python -m unittest tests.test_build -v`. Esperado: FAIL.
- [ ] **Paso 3:** implementar `mbl/build.py` y `mbl/__main__.py` con `argparse`.
- [ ] **Paso 4:** volver a ejecutar los tests. Esperado: PASS.
- [ ] **Paso 5: prueba real.** Ejecutar `python -m mbl build --sources sources.toml --allowlist allowlist.txt --out dist`. Esperado:
  - código 0;
  - un total de entradas entre 5000 y 150000, apuntado en el commit;
  - `grep -cE '^add ' dist/blocklist.rsc` coincide con el total.
- [ ] **Paso 6:** commit: `feat: build CLI`.

### Tarea 7: Workflow de GitHub Actions

**Ficheros:**
- Crear: `.github/workflows/build.yml`

**Contenido decidido:**
- **Disparadores:** `schedule: cron "17 4 * * *"`, `workflow_dispatch`, `push` a `main` y `pull_request`.
- **Job `test`:** `actions/checkout@v4` y `actions/setup-python@v5` con `3.12`, y después `python -m unittest discover -v`.
- **Job `publish`:**
  - depende de `test` (`needs: test`);
  - solo se ejecuta si `github.ref == 'refs/heads/main' && github.event_name != 'pull_request'`;
  - `permissions: contents: write`, así que no hace falta tocar la configuración del repo: un `permissions` explícito en el workflow eleva el token aunque el valor por defecto sea solo lectura;
  - `concurrency: publish`.

  Pasos del job:
  1. Ejecutar el build con `--previous-stats https://raw.githubusercontent.com/${{ github.repository }}/lists/stats.json`.
  2. Dentro de `dist/`:
     ```
     git init -b lists
     git add .
     git commit -m "lists: <fecha>"
     git push -f https://x-access-token:${{ secrets.GITHUB_TOKEN }}@github.com/${{ github.repository }} lists
     ```
     Como autor, `github-actions[bot]`.
  3. Si el build devuelve 1, el job falla y no se publica nada.

- [ ] **Paso 1:** escribir el workflow.
- [ ] **Paso 2:** validar la sintaxis con `python -c "import yaml"`. Si `pyyaml` no está disponible, usar `npx --yes @action-validator/cli .github/workflows/build.yml`. Si ninguna de las dos funciona, se revisa a mano y se valida en la Tarea 10, cuando se ejecute de verdad.
- [ ] **Paso 3:** commit: `ci: daily build and publish to lists branch`.

### Tarea 8: Scripts RouterOS

**Ficheros:**
- Crear: `routeros/install.rsc`, `routeros/uninstall.rsc`

**Comportamiento decidido de `install.rsc`:**
1. **Comprobaciones previas.** El script aborta con `:error` y un mensaje claro, sin crear nada, si:
   - la versión de RouterOS no es la 7.x mínima (se fija en la Tarea 9);
   - no existe la interface-list `WAN`;
   - no existe la interface-list `LAN`.
2. **HTTPS.** Habilitar la validación de certificados con el almacén integrado de v7. Si la versión mínima no lo tiene, importar la CA raíz que usa `raw.githubusercontent.com`. Esto se decide en la Tarea 9.
3. **Limpieza.** Eliminar todo lo de una instalación anterior:
   - scripts y schedulers cuyo nombre empiece por `mbl-`;
   - reglas raw con comentario `MBL:`;
   - entradas de `mbl-a` y `mbl-b`.

   Las entradas `MBL: admin` de `mbl-allow` se conservan.
4. **Allowlist de administración.** Añadir a `mbl-allow` la `address` de cada `/user active` que no esté vacía, con el comentario `MBL: admin`. Las duplicadas se omiten con `:do {} on-error={}`.
5. **Script `mbl-update`.** Tiene que hacer lo siguiente, en este orden:
   1. **Lock.** Si `:global mblRunning` es true, sale. Si no, la pone a true y la libera también en los caminos de error.
   2. **Origen.** Con el argumento `source=boot` (variable global `mblBoot`) usa el fichero `mbl-last.rsc` existente y no descarga. En otro caso descarga `/tool fetch url=<URL> dst-path=mbl-new.rsc check-certificate=yes`, envuelto en `:do {} on-error={ log; salir }`.
   3. **Tamaño.** Comprueba `[/file get mbl-new.rsc size] >= 100000`. Si no se cumple, borra el fichero, lo registra en el log y sale.
   4. **Importación.** Calcula `target`: la lista que **no** usa ahora la regla `MBL: in`, o `mbl-a` si no hay ninguna. Después ejecuta:
      ```
      :global mblTarget $target
      :global mblImportOk false
      /ip firewall address-list remove [find list=$target]
      /import file-name=mbl-new.rsc verbose=no
      ```
   5. **Validación.** Si `mblImportOk != true` o `[:len [find list=$target]] < 1000`:
      - vacía `target`;
      - si no es el arranque, borra el fichero nuevo;
      - lo registra en el log y sale.

      La lista activa no se toca.
   6. **Cambio.** Pasa a `target` las tres reglas `MBL: in`, `MBL: out` y `MBL: router-out` (`src-address-list` o `dst-address-list` según la regla). Después vacía la lista antigua.
   7. **Copia.** Si no es el arranque, sustituye `mbl-last.rsc` por `mbl-new.rsc`.
   8. **Resumen.** Escribe en el log `MBL: loaded <n> entries into <target>`.
6. **Schedulers.**
   - `mbl-daily`: `interval=1d`, con hora `start-time` aleatoria (`[:rndnum from=0 to=86399]` segundos, formateados `HH:MM:SS`), ejecuta `mbl-update`.
   - `mbl-boot`: `start-time=startup`. Ejecuta `mbl-update` en modo arranque, espera 60 s y lo ejecuta en modo normal.
7. **Reglas.** En `/ip firewall raw`, añadidas al principio (`place-before=0` si ya hay reglas) y en este orden:

   | Cadena | Condición | Acción | Comentario |
   |---|---|---|---|
   | prerouting | `src-address-list=mbl-allow` | accept | `MBL: allow-in` |
   | prerouting | `dst-address-list=mbl-allow` | accept | `MBL: allow-out` |
   | prerouting | `in-interface-list=WAN src-address-list=mbl-a` | drop | `MBL: in` |
   | prerouting | `in-interface-list=LAN dst-address-list=mbl-a` | drop, `log=yes log-prefix="MBL-OUT"` | `MBL: out` |
   | output | `dst-address-list=mbl-a` | drop | `MBL: router-out` |

8. **Primera carga.** Ejecuta `mbl-update`, borra `install.rsc` y escribe en el log `MBL: installed`.

**`uninstall.rsc`:** borra:
- los scripts y schedulers `mbl-*`;
- las reglas `MBL:`;
- las listas `mbl-a`, `mbl-b` y `mbl-allow` (solo las entradas `MBL: admin`; las que haya añadido el usuario se conservan);
- los ficheros `mbl-*.rsc`.

- [ ] **Paso 1:** escribir `routeros/install.rsc` y `routeros/uninstall.rsc`. La URL de la lista va en una variable al principio del instalador, para que un fork pueda cambiarla.
- [ ] **Paso 2:** commit: `feat: RouterOS v7 installer and uninstaller`. La validación real es la Tarea 9.

### Tarea 9: Validación en CHR v7 (Proxmox del usuario)

**Ficheros:**
- Crear: `docs/testing-chr.md` (cómo montar la VM y la lista de casos)
- Modificar: `routeros/*.rsc` según lo que salga de las pruebas

- [ ] **Paso 1: instrucciones para el usuario** en `docs/testing-chr.md`:
  - descargar la imagen CHR v7 *stable* de mikrotik.com;
  - importarla en Proxmox con `qm importdisk`;
  - darle 2 NIC: `ether1` (WAN, con salida a Internet) y `ether2` (LAN);
  - crear las interface-lists `WAN` y `LAN` y asignar `ether1` y `ether2` respectivamente;
  - activar SSH con la clave pública de este equipo (`/user ssh-keys import`).

  **El usuario hace estos pasos y facilita la IP.**
- [ ] **Paso 2:** fijar la versión mínima. Comprobar en el CHR, por SSH, que funcionan:
  - el almacén de certificados integrado;
  - `/file get … size`;
  - `[:rndnum]`;
  - `place-before`;
  - el cambio de `src-address-list` sobre reglas raw.

  Documentar la versión mínima en `install.rsc` y en el README.
- [ ] **Paso 3:** publicar una lista de prueba. Generar `dist/` en local y servirla por HTTPS. Mientras no exista la rama `lists`, se puede subir temporalmente a la rama `lists-test` del repo; solo es un push de rama, que el usuario ha autorizado.
- [ ] **Paso 4: casos de prueba por SSH.** Cada uno se apunta como OK/FALLO en `docs/testing-chr.md`:
  1. **Instalación limpia:** existen las 5 reglas, los 2 schedulers y el script, y `mbl-a` tiene ≥ 1000 entradas.
  2. **Bloqueo entrante:** con una IP de la lista añadida a mano, `MBL: in` cuenta paquetes. Comprobarlo con `/tool fetch` desde un host de prueba o mirando los contadores.
  3. **Bloqueo saliente:** un `ping` desde la LAN a una IP de la lista aparece en el log como `MBL-OUT`. Desde el propio router, `/ping` se bloquea por `MBL: router-out`.
  4. **Actualización:** ejecutar `mbl-update` cambia las reglas a `mbl-b` y deja `mbl-a` vacía.
  5. **Fichero truncado:** se sirve un `.rsc` sin el pie. Se mantiene la lista anterior y aparece un error en el log.
  6. **URL caída:** se mantiene la lista anterior.
  7. **Ejecución concurrente:** dos `mbl-update` seguidos con `/system script run`. El segundo sale por el lock.
  8. **Reinicio con red:** tras arrancar, la lista se carga desde `mbl-last.rsc` en segundos y luego se actualiza.
  9. **Arranque sin red:** con `ether1` desactivada y reinicio, la lista se carga desde `mbl-last.rsc`.
  10. **Reinstalación:** no duplica nada y conserva `MBL: admin`.
  11. **IP de gestión listada:** con la IP del admin en `mbl-a`, se sigue teniendo acceso SSH.
  12. **Desinstalación:** no queda nada `mbl` y la configuración del usuario sigue intacta.
  13. **Rendimiento:** se mide el tiempo de importación y la RAM con la lista real (`/system resource print` antes y después).
- [ ] **Paso 5:** corregir los scripts hasta que los 13 casos estén en OK y borrar la rama `lists-test`.
- [ ] **Paso 6:** commit: `test: validate RouterOS scripts on CHR v7`.

### Tarea 10: README atractivo y publicación

**Ficheros:**
- Crear: `README.md` (reescrito), `docs/assets/banner.svg`

**Contenido decidido del README (en inglés, con sección "🇪🇸 Español" al final):**
- **Cabecera** centrada: el banner SVG (escudo con el router y el nombre; propio, sin logos de terceros) y una línea de descripción.
- **Badges:**
  - el workflow (`actions/workflows/build.yml/badge.svg`);
  - `https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/Psycomy/MikrotikBlockList/lists/badge-entries.json`, y lo mismo con `badge-updated.json`;
  - la licencia GPL-3.0;
  - la versión mínima de RouterOS.
- **Aviso** `> [!WARNING]`: *For home / non-commercial use only — several sources forbid commercial use.*
- **Diagrama Mermaid:** `Sources → GitHub Action (daily) → lists branch → MikroTik (raw firewall)`.
- **Instalación** en una línea copiable.
- **Qué se crea:** tabla de las 5 reglas y para qué sirve cada una.
- **Ver bloqueos:** `/log print where message~"MBL-OUT"` y los contadores.
- **Allowlist:** `/ip firewall address-list add list=mbl-allow address=…`.
- **Desinstalación.**
- **Tabla de fuentes:** nombre, categoría y licencia (desde `license_note`).
- **Bloques `<details>`:** cómo funciona la actualización (listas alternas, `mbl-last.rsc`), FAQ y forks (cambiar la URL).

**Pasos:**
- [ ] **Paso 1:** escribir `docs/assets/banner.svg` y `README.md`.
- [ ] **Paso 2:** commit: `docs: new README`.
- [ ] **Paso 3:** **avisar en el chat** e integrar la rama: `git switch main && git merge --ff-only v2 && git push origin main`. Autorizado por el usuario.
- [ ] **Paso 4:** lanzar `gh workflow run build.yml` y seguirlo con `gh run watch` (es una sola ejecución que se espera, no un sondeo periódico). Esperado:
  - el job `publish` termina en verde;
  - `curl -s https://raw.githubusercontent.com/Psycomy/MikrotikBlockList/lists/stats.json` devuelve el `total`.
- [ ] **Paso 5:** comprobar en GitHub que los badges de entradas y fecha se ven en el README.
- [ ] **Paso 6: prueba final en el CHR** con la URL real. Reinstalar con el one-liner del README y repetir los casos 1, 4 y 8 de la Tarea 9.
