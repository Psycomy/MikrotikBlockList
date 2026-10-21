# v3 Fase 6 — Mejoras menores · Plan de implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Objetivo:** cerrar la v3 con estos puntos:
- allowlist automática de los CDN;
- reinstalación sin ningún hueco sin reglas;
- dos endurecimientos pequeños del CI y de las pruebas;
- plantillas de issues;
- guía de seguridad de la cuenta;
- pulido de la documentación.

**Arquitectura:**
- **Generador:** descarga en cada build los rangos oficiales de Cloudflare, Fastly y CloudFront y los valida. Si un proveedor falla, usa una copia guardada en el repo. Los resta junto con la allowlist estática y vigila que no se coman más del 10 % de la lista.
- **Instalador:** marca las reglas viejas en lugar de borrarlas; crea las nuevas y solo entonces quita las viejas.

**Tecnología:** Python 3.12 con la biblioteca estándar, scripting de RouterOS v7, GitHub Actions y Markdown.

**Spec:** `docs/superpowers/specs/2026-10-21-mbl-v3-hardening-design.md`, fase 6 y §7.9.

## Restricciones globales

### Allowlist de CDN (§7.9)

**Fuentes:**

| Proveedor | URL | Qué se toma |
|---|---|---|
| Cloudflare | `https://www.cloudflare.com/ips-v4` y `https://www.cloudflare.com/ips-v6` | todas las líneas |
| Fastly | `https://api.fastly.com/public-ip-list` | `addresses` y `ipv6_addresses` |
| CloudFront | `https://ip-ranges.amazonaws.com/ip-ranges.json` | `ip_prefix` de `prefixes` con `service == "CLOUDFRONT"`, e `ipv6_prefix` de `ipv6_prefixes` con el mismo servicio |

**Validación por proveedor y familia.** La descarga se rechaza si:
- no se puede leer;
- trae menos de 5 prefijos IPv4;
- algún prefijo IPv4 es más amplio que /8;
- algún prefijo IPv6 es más amplio que /16.

Para IPv6 basta con 1 prefijo.

**Copia guardada:** `allowlist-cdn.snapshot.txt` en la raíz.
- Formato: cabecera `# provider <nombre> <fecha>` y un CIDR por línea, por bloques de proveedor.
- Si un proveedor se rechaza, se usa su bloque de la copia y se avisa por stderr y en el *step summary*. Si tampoco está en la copia, el build sigue **sin** ese proveedor y avisa igualmente.
- La copia se actualiza con `python -m mbl cdn-snapshot --out allowlist-cdn.snapshot.txt`, a mano y mediante PR. **El workflow nunca hace commit en `main`.**

**`allowlist.txt`:**
- se quitan los rangos de Cloudflare puestos a mano (IPv4 e IPv6), que ahora vienen de forma automática;
- se quedan el rango de GitHub y los DNS públicos.

**Tope del 10 %:**
- Si la allowlist (estática más CDN) elimina más del 10 % de las direcciones de la variante IPv4 *full*, el build falla con código 1.
- Para IPv6, lo mismo con la variante IPv6 *full*: se retiene IPv6 (mejor esfuerzo), sin código 1.
- La medida: direcciones antes y después de restar la allowlist, sobre la lista ya normalizada sin allowlist.

**`stats.json`:** se añade `"cdn_allowlist": {"<proveedor>": {"source": "live"|"snapshot"|"missing", "prefixes4": N, "prefixes6": M}}`.

### Router

- **Reinstalación sin hueco** *(VERSION `3.3.1`)*:
  1. En el paso de limpieza, las reglas `MBL:` existentes (IPv4 y, si las hay, IPv6) **no se borran**: se les cambia el comentario a `MBL-OLD: <comentario anterior>`.
  2. Se crean las reglas nuevas en su sitio.
  3. Solo entonces se borran las `^MBL-OLD:`.
  4. Si la instalación aborta a mitad, las `MBL-OLD:` siguen protegiendo. La siguiente instalación y la desinstalación también borran `^MBL-OLD:`.
  5. `mbl-update` sigue buscando solo `comment="MBL: in"`, etc.

### CI y pruebas

- **Input del workflow manual:** se valida con `[[ $version =~ ^[0-9]+(\.[0-9]+)+([a-z]+[0-9]+)?$ ]]` de bash, que no acepta cadenas multilínea. Se aplica a la versión resuelta, sea cual sea su origen.
- **e2e:** la limpieza `atexit` y de clase del modo "host existente" también borra las entradas `/ip dns static` con `comment="MBLTEST"`.

## Puntos de revisión

1. **Un proveedor CDN devuelve HTML** (página de error con 200). Se rechaza y se usa la copia. Lo cubre la Tarea 1: `test_cdn_html_falls_back_to_snapshot`.
2. **Un proveedor devuelve `0.0.0.0/0` o `::/0`.** Se rechaza: nunca debe vaciar la lista. Lo cubre la Tarea 1: `test_cdn_rejects_too_wide`.
3. **La allowlist elimina el 11 %.** El build falla. Lo cubre la Tarea 1: `test_allowlist_cap_fails_build`.
4. **La reinstalación nunca deja 0 reglas `MBL: in`.** Lo cubre la Tarea 2: `test_10` con el muestreo concurrente sin tolerancia (0 muestras sin regla) también en la reinstalación v3→v3, y un caso nuevo `test_07b_reinstall_no_rule_gap`.
5. **Una instalación abortada deja reglas `MBL-OLD:`.** La siguiente instalación las borra. Lo cubre la Tarea 2: `test_07c_old_rules_cleaned`, que crea a mano una regla `MBL-OLD: in` y comprueba que la instalación la elimina.
---

### Tarea 1: Allowlist automática de CDN

**Ficheros:**
- Crear: `mbl/cdn.py`, `allowlist-cdn.snapshot.txt`
- Modificar: `mbl/build.py`, `mbl/__main__.py`, `mbl/render.py` (sección `cdn_allowlist` de `stats.json`), `allowlist.txt`
- Test: `tests/test_cdn.py`, `tests/test_build.py`

**Interfaces:**
- `cdn.PROVIDERS`: los tres proveedores, con sus URL y funciones de extracción.
- `cdn.fetch_cdn(snapshot_path: Path, fetcher=urlopen-like, backoff=...) -> CdnResult`. `CdnResult` lleva `networks: list[IPv4Network | IPv6Network]` e `info: dict[str, dict]`.
- `cdn.write_snapshot(path: Path, ...) -> None`.
- CLI: `python -m mbl cdn-snapshot --out PATH`.
- `build(...)` añade las redes CDN a la allowlist y aplica el tope del 10 %.

- [ ] **Paso 1: tests que fallan.**
  - Extracción de cada proveedor a partir de fixtures reales recortados: `tests/fixtures/cdn_*`.
  - `test_cdn_html_falls_back_to_snapshot`.
  - `test_cdn_rejects_too_wide`: `0.0.0.0/0`, `10.0.0.0/7` y `::/0`.
  - `test_cdn_too_few_ipv4_rejected`.
  - `test_cdn_missing_everywhere_warns_and_continues`.
  - `test_allowlist_cap_fails_build`: una allowlist que elimina el 11 % da código 1.
  - `test_allowlist_cap_ipv6_withholds`.
  - `test_stats_cdn_allowlist`.
  - `test_cdn_snapshot_cli`.
- [ ] **Paso 2:** ejecutarlos. Esperado: FAIL.
- [ ] **Paso 3:** implementar. Generar `allowlist-cdn.snapshot.txt` real con el CLI y quitar Cloudflare de `allowlist.txt`.
- [ ] **Paso 4:** `python3 -m unittest discover` en verde. En un build real, apuntar cuántas entradas *full* IPv4 e IPv6 quita la allowlist.
- [ ] **Paso 5:** commit: `feat(build): automatic CDN allowlist with snapshot fallback`.

### Tarea 2: Reinstalación sin hueco y endurecimientos

**Ficheros:**
- Modificar: `routeros/install.rsc`, `routeros/uninstall.rsc`, `VERSION` (`3.3.1`), `.github/workflows/routeros-e2e.yml`, `tests/e2e/test_routeros.py`

- [ ] **Paso 1: instalador y desinstalador**, según el apartado "Router". Subir `VERSION` y `mblScriptVersion` a `3.3.1`. Comprobar el equilibrio de llaves: `0 0`.
- [ ] **Paso 2: workflow.** Validación `[[ =~ ]]`. Pasar el action-validator.
- [ ] **Paso 3: e2e.**
  - Limpieza de las entradas DNS `MBLTEST`.
  - El muestreo de `test_10` sin tolerancia.
  - Caso `test_07b_reinstall_no_rule_gap`: muestreo concurrente durante una reinstalación v3→v3; todas las muestras con regla `MBL: in` y ≥1000 entradas.
  - Caso `test_07c_old_rules_cleaned`: con una regla `MBL-OLD: in` creada a mano, la instalación la borra.
  - `test_15` comprueba que no queda ninguna `MBL-OLD:`.
- [ ] **Paso 4:** e2e local completo en verde. `python3 -m unittest discover` en verde.
- [ ] **Paso 5:** commit: `fix(routeros): reinstall without a rule gap`.

### Tarea 3: Plantillas, seguridad y documentación

**Ficheros:**
- Crear: `.github/ISSUE_TEMPLATE/false_positive.yml`, `.github/ISSUE_TEMPLATE/bug.yml`, `.github/ISSUE_TEMPLATE/config.yml`, `docs/security.md`
- Modificar: `README.md` (inglés y español), `CHANGELOG.md` (`3.3.1`)

- [ ] **Paso 1: plantillas en formato *issue forms*.**
  - **Falso positivo:** IP o CIDR (obligatorio), variante y familia, fuente si se conoce (desplegable con las fuentes del catálogo, más "no sé"), qué dejó de funcionar y una casilla de "he comprobado que no es mi allowlist local".
  - **Bug:** versión del script (`MBL: installed (script …)`), versión de RouterOS, modelo, salida de `/log print where message~"MBL"`, pasos para reproducirlo.
  - **`config.yml`:** `blank_issues_enabled: false`.
- [ ] **Paso 2: `docs/security.md`**, en inglés con resumen en español.
  - El modelo de amenaza: el router no ejecuta nada descargado; una cuenta comprometida podría publicar listas falsas, con los límites que eso tiene (bloquear IPs, no ejecutar).
  - Lo que hace el usuario, con enlaces a la configuración de GitHub: 2FA, *rulesets* o protección de `main` (PR obligatorio y estado `test` y `e2e` requerido), permisos de Actions (*read*, salvo `publish`), restringir quién puede lanzar workflows y revisar los tokens y las *deploy keys*.
  - Cómo informar de una vulnerabilidad.
- [ ] **Paso 3: README.**
  - Diagrama Mermaid con las dos familias y las dos variantes.
  - Cifras de la publicación actual (lee `lists/stats.json`).
  - En la tabla en inglés, que `blocklist.rsc` es solo *full*.
  - Enlaces a `docs/security.md` y a las plantillas.
  - Sección de la allowlist automática de CDN.
  - Lo mismo en la sección en español.
- [ ] **Paso 4: CHANGELOG `3.3.1`.**
- [ ] **Paso 5:** commit: `docs: issue templates, security guide, README polish`.
- [ ] **Paso 6: lo hace el controlador.** Push, PR, e2e en verde, merge. Comprobar la publicación (`script=3.3.1` y `stats.cdn_allowlist` con tres proveedores `live`) y reinstalar el CHR del usuario.
