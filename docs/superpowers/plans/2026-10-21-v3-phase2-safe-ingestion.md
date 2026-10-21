# v3 Fase 2 — Ingesta segura sin `/import` · Plan de implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Objetivo:** que el router deje de ejecutar código descargado. En lugar de hacer `/import` de un `.rsc`, `mbl-update` descarga una lista en texto plano, valida cada línea como IPv4 o CIDR y añade solo esos datos.

**Arquitectura:**
- **Generador:** publica además `routeros-full.txt`, con una cabecera y un pie que llevan el número de entradas. `blocklist.rsc` y `blocklist.txt` siguen igual.
- **Router:** `mbl-update` lee el fichero por trozos (`/file read … as-value`), procesa las líneas teniendo en cuenta las que quedan cortadas entre trozos, valida cada una y hace `add` en la lista inactiva.
- **Se mantiene igual que en v2:** listas alternas, copia de arranque (ahora `mbl-last.txt`), lock, prefijo `flash/` y "la lista activa nunca se vacía".
- **Actualización desde v2:** basta con reinstalar.

**Tecnología:** Python 3.12 con la biblioteca estándar, scripting de RouterOS v7 (≥ 7.21) y el harness e2e de la fase 1.

**Spec:** `docs/superpowers/specs/2026-10-21-mbl-v3-hardening-design.md`. Aplican la fase 2 y las decisiones §7.2, §7.6 y §7.10.

## Restricciones globales

- **Formato de `routeros-full.txt`** (exacto, `\n` como fin de línea, salto final tras el pie):
  ```
  # MikrotikBlockList v3 format=1 variant=full family=ipv4 generated=<YYYY-MM-DDTHH:MM:SSZ> entries=<N> script=<VERSION>
  <una dirección por línea: IP sin /32, o CIDR>
  # MBL-END entries=<N>
  ```
- **`VERSION`:** fichero en la raíz con `3.0.0\n`. El generador lo lee y lo pone en `script=`.
- **Ficheros para otros firewalls:** `blocklist.txt` sigue siendo una entrada por línea **sin** cabecera. `blocklist.rsc` sigue publicándose **sin cambios** para los routers con v2, al menos hasta 2027-04-30.
- **El router nunca ejecuta contenido del fichero.** No hay `/import`, ni `:parse` ni `:execute` sobre datos leídos. Cada línea es solo un valor que se valida con `:toip` y con la comprobación del prefijo.
- **Validación de línea:**
  - si empieza por `#`, es la cabecera (primera línea) o el pie;
  - si no, debe tener la forma `a.b.c.d` o `a.b.c.d/p`, con `[:typeof [:toip a.b.c.d]] = "ip"` y `p` un entero entre 8 y 32;
  - el resto de líneas cuentan como inválidas y no se añaden.
- **Rechazo de la carga:** se vacía la lista destino y la activa no se toca si ocurre cualquiera de estas cosas:
  - la cabecera falta o no trae `format=1` y `family=ipv4`;
  - falta el pie;
  - `entries` de la cabecera ≠ `entries` del pie;
  - añadidas ≠ `entries`;
  - inválidas > 1 % de `entries`;
  - añadidas < 1000.
- **Ficheros en el router:**
  - `mbl-new.txt`, siempre en la raíz (RAM);
  - `mbl-last.txt` y `mbl-tmp.txt`, con el prefijo `flash/` si existe el directorio.
- **Base de las URL:**
  - `:local mblBase "https://raw.githubusercontent.com/Psycomy/MikrotikBlockList/lists"`;
  - la global de pruebas `mblUrlBase`, si no está vacía, sustituye a `mblBase`;
  - el script descarga `$base . "/routeros-full.txt"`.
- **Actualización desde v2:** el instalador v3 **no vacía** las listas. Los ficheros `mbl-last.rsc` y `mbl-tmp.rsc` antiguos se borran solo **tras** la primera carga v3 correcta, y desde el propio `mbl-update`: si la carga fue bien y existe algún `*.rsc` con prefijo `mbl-`, se borra.
- **Rendimiento:** actualización completa de unas 39k entradas en ≤ 5 min en el CHR de 1 vCPU. Se mide y se apunta en `docs/testing-chr.md`. Si no se cumple, se optimiza (trozos más grandes, menos llamadas), **sin volver a `/import`**. Si aun así no se llega, se para y se informa.
- **Etiqueta `v2.0.0`:** ya existe en GitHub. El CI la usa para probar la actualización.

## Puntos de revisión

1. **Una línea cortada entre dos trozos de `/file read`.** No debe contar como inválida ni partirse en dos direcciones. Lo cubre la Tarea 2: el e2e con lista real carga exactamente `entries`, con 0 inválidas (`test_01`).
2. **Contenido que intenta ejecutar comandos** (`/system reboot`, `1.2.3.4; /ip …`, `$(…)`, `[…]`). Nunca se ejecuta: cuenta como inválido. Lo cubre la Tarea 3: `test_11_injected_lines_never_run`.
3. **Cabecera y pie coherentes pero con menos entradas de las que dicen** (archivo cortado justo antes del pie y con el pie añadido a mano). Se rechaza. Lo cubre la Tarea 3: `test_12_count_mismatch_rejected`.
4. **Router con v2 instalado.** Al reinstalar, mantiene la protección en todo momento, borra los `.rsc` viejos solo tras la primera carga correcta y no deja reglas apuntando a una lista vacía. Lo cubre la Tarea 3: `test_10_upgrade_from_v2`.
5. **Ficheros con CRLF o espacios al final** (alguien que sirve la lista desde otro sitio). Las líneas se aceptan quitando `\r` y espacios finales. Lo cubre la Tarea 3: `test_13_crlf_accepted`.

---

### Tarea 1: Generador — `VERSION` y `routeros-full.txt`

**Ficheros:**
- Crear: `VERSION`
- Modificar: `mbl/render.py`, `mbl/build.py`, `mbl/__main__.py`
- Test: `tests/test_render.py`, `tests/test_build.py`

**Interfaces:**
- Produce `render.router_txt(addresses: list[str], stamp: str, script_version: str, variant: str = "full", family: str = "ipv4") -> str`, con el formato exacto de las restricciones globales.
- `write_outputs(out_dir, networks, results, generated_at, script_version: str = "0.0.0")` también escribe `routeros-full.txt`.
- `build(..., version_path: Path = Path("VERSION"))` lee la versión (con `strip()`) y la pasa a `write_outputs`. Si el fichero no existe o está vacío, devuelve 2 (error de configuración).
- CLI: `--version-file`, con `VERSION` por defecto.

- [ ] **Paso 1: tests que fallan.**
  - `test_router_txt_format`: con `["1.2.3.4", "5.6.0.0/16"]`, stamp `2026-10-21T04:17:00Z` y version `3.0.0`, la salida es exactamente la cabecera indicada, las dos líneas y `# MBL-END entries=2`, con salto final.
  - `test_write_outputs_writes_router_txt`: existe `routeros-full.txt` y sus líneas de datos son iguales a las de `blocklist.txt`.
  - `test_blocklist_txt_has_no_header`: la primera línea de `blocklist.txt` no empieza por `#`.
  - `test_build_reads_version`: con un `VERSION` temporal `9.8.7`, `routeros-full.txt` contiene `script=9.8.7`.
  - `test_build_missing_version_returns_2`.
- [ ] **Paso 2:** `python3 -m unittest tests.test_render tests.test_build -v`. Esperado: FAIL.
- [ ] **Paso 3:** implementar. Crear `VERSION` con `3.0.0`.
- [ ] **Paso 4:** `python3 -m unittest discover`. Esperado: OK (e2e *skipped*).
- [ ] **Paso 5:** commit: `feat(render): publish routeros-full.txt and VERSION`.

### Tarea 2: Router — `mbl-update` sin `/import`

**Ficheros:**
- Modificar: `routeros/install.rsc` (ajustes y secciones 3, 5 y 8), `routeros/uninstall.rsc`
- Modificar: `tests/e2e/test_routeros.py` (adaptar los 9 casos existentes al nuevo formato)

**Interfaces:**
- Consume `routeros-full.txt`, de la Tarea 1.
- Produce los mensajes de log nuevos. Los casos de la Tarea 3 dependen de estos textos exactos:
  - `MBL: loaded <n> entries into <list> (list generated <stamp>)` (igual que en v2);
  - `MBL: <fname> rejected (<motivo>), active list kept`, donde `<motivo>` es uno de: `no header`, `bad header`, `no footer`, `count mismatch`, `too many invalid lines (<k>)` o `too few entries (<n>)`;
  - `MBL: download failed (<url>), list not changed` (igual que en v2);
  - `MBL: removed v2 files` (tras la primera carga v3 con `.rsc` antiguos presentes).

- [ ] **Paso 1: instalador.**
  - Cambiar los ajustes a `mblBase` + `mblUrlBase` → `$url = base . "/routeros-full.txt"`. Se conserva el aviso `MBL: using test URL base`.
  - Paso 3 (limpieza de la instalación anterior): no borrar ficheros `mbl-*.rsc`. Eso lo hace `mbl-update` después de una carga correcta.
  - Cabecera del instalador: pasar a `MikrotikBlockList v3`.
- [ ] **Paso 2: `mbl-update`.** Sustituir las secciones "header" e "import into the list…" y "validate" por el lector por trozos:
  - el tamaño de trozo y el bucle los decide el implementador;
  - tiene que tener en cuenta la línea partida entre trozos y quitar `\r` y los espacios finales;
  - los rechazos son los de las restricciones globales, con los mensajes de arriba;
  - se mantienen igual la comprobación de tamaño mínimo (100.000 bytes), el lock, el cálculo de `target` y `old`, el cambio de reglas y el aviso de lista antigua;
  - el bloque de copia de arranque pasa a usar `.txt`;
  - tras una carga correcta, borrar `mbl-last.rsc` y `mbl-tmp.rsc` (en la raíz y en `flash/`) si existen, y escribir en el log `MBL: removed v2 files`.
- [ ] **Paso 3: `uninstall.rsc`.** La expresión de ficheros pasa a `^(flash/)?mbl-.*\.(rsc|txt)$`.
- [ ] **Paso 4:** comprobación de equilibrio de `install.rsc`. Esperado: `0 0`.
- [ ] **Paso 5: adaptar `tests/e2e/test_routeros.py`.**
  - La lista servida es la que genera `write_outputs` (que ya incluye `routeros-full.txt`).
  - `blocklist-truncated` pasa a ser `routeros-full-truncated.txt`: el mismo fichero sin la última línea (el pie).
  - test_03 espera `rejected (no footer)`.
  - test_06 espera `flash/mbl-last.txt`.
  - test_08 comprueba que no queda ningún `mbl-*.txt` ni `mbl-*.rsc`.
  - test_09 espera `…/lists/routeros-full.txt`.
- [ ] **Paso 6: ejecución real local.** `MBL_E2E=1 MBL_E2E_CACHE=<cache> python3 -m unittest tests.e2e.test_routeros -v`. Esperado: 9/9. Pegar en el informe el tiempo de test_02 (actualización completa de 5.000 entradas).
- [ ] **Paso 7: medida de rendimiento con tamaño real.**
  - Generar con `write_outputs` una lista de 40.000 `/32` consecutivas desde `45.0.0.0` y servirla.
  - Ejecutar `mbl-update` en el CHR local y medir el tiempo y la RAM libre antes y después, con `/system resource get free-memory`.
  - Esperado: ≤ 5 min. Si no se cumple, optimizar y repetir. Si no se llega, parar con `BLOCKED` y adjuntar los datos.
- [ ] **Paso 8:** commit: `feat(routeros): v3 updater reads and validates a plain list, no /import`.

### Tarea 3: Casos e2e nuevos de seguridad y actualización

**Ficheros:**
- Modificar: `tests/e2e/test_routeros.py`

**Interfaces:**
- Consume el harness de la fase 1 y los mensajes de la Tarea 2.
- El instalador v2 se obtiene con `git show v2.0.0:routeros/install.rsc`, mediante `subprocess` desde la raíz del repo.

**Casos** (después de los 9 existentes, antes de la desinstalación final; el implementador puede renumerar para conservar el orden):
- `test_10_upgrade_from_v2`:
  1. Desinstalar.
  2. Instalar con el `install.rsc` de `v2.0.0`, con `mblUrlBase` apuntando al servidor, que sigue sirviendo `blocklist.rsc`.
  3. Comprobar que existe `mbl-last.rsc`.
  4. Instalar con el v3.
  5. Comprobar que durante todo el proceso la regla `MBL: in` apunta a una lista con ≥1000 entradas: se mide antes y después de la reinstalación y justo tras ella.
  6. Tras la primera carga v3: el log contiene `MBL: removed v2 files`, no existe ningún `mbl-*.rsc` y existe `mbl-last.txt`.
- `test_11_injected_lines_never_run`: servir una variante válida de `routeros-full.txt` con 5.000 entradas a la que se añaden 10 líneas maliciosas (menos del 1 %), sin cambiar `entries`. Las líneas son:
  - `/ip firewall address-list add list=mbl-pwned address=1.1.1.1`
  - `1.2.3.4; /ip firewall address-list add list=mbl-pwned address=1.1.1.2`
  - `$([/ip firewall address-list add list=mbl-pwned address=1.1.1.3])`
  - `[/ip firewall address-list add list=mbl-pwned address=1.1.1.4]`
  - `:execute "/ip firewall address-list add list=mbl-pwned address=1.1.1.5"`
  - `999.1.1.1`
  - `1.2.3.0/40`
  - `1.2.3.0/4`
  - `abc`
  - una línea vacía

  Tras `mbl-update`: `count("mbl-pwned") == 0`, la carga es correcta (las inválidas no superan el 1 %) y la lista activa tiene exactamente 5.000 entradas.
- `test_12_count_mismatch_rejected`: un fichero con 5.000 entradas cuya cabecera y pie dicen `entries=5100`. Se rechaza con `count mismatch`, y la lista y su número de entradas no cambian.
- `test_13_crlf_accepted`: el mismo `routeros-full.txt`, con `\r\n` en lugar de `\n` y un espacio final en 10 líneas. Carga 5.000 entradas y 0 inválidas.
- `test_14_too_many_invalid_rejected`: 5.000 válidas más 100 inválidas (2 %), con `entries=5000`. Se rechaza con `too many invalid lines`.

- [ ] **Paso 1:** escribir los casos.
- [ ] **Paso 2: ejecución real local.** Esperado: todos OK (9 adaptados + 5 nuevos).
- [ ] **Paso 3:** `python3 -m unittest discover`. Esperado: OK (e2e *skipped*).
- [ ] **Paso 4:** commit: `test(e2e): v2 upgrade, injection, count, CRLF and invalid-ratio cases`.

### Tarea 4: Documentación y PR

**Ficheros:**
- Modificar: `README.md` (inglés y español), `docs/testing-chr.md`

- [ ] **Paso 1: README.**
  - **Cómo funciona:** el router valida cada línea y no ejecuta nada.
  - **Ficheros publicados:** añadir `routeros-full.txt` (lo usa el router) y `blocklist.rsc` (legado de la v2, se mantiene hasta 2027-04-30).
  - **Actualizar desde la v2:** "vuelve a ejecutar el mismo comando de instalación".
  - Tiempos y RAM medidos en la Tarea 2.
  - En la sección en español, lo mismo.
- [ ] **Paso 2: `docs/testing-chr.md`.** Casos 10-14 y la medida de rendimiento (fecha, entradas, tiempo, RAM).
- [ ] **Paso 3:** commit: `docs: v3 safe ingestion and upgrade path`.
- [ ] **Paso 4: lo hace el controlador.** Push, PR, e2e en verde en el PR y, con permiso del usuario, una ejecución contra el CHR de Proxmox (`MBL_E2E_DESTRUCTIVE=1`) y reinstalación posterior con el instalador publicado.
