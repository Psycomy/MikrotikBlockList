# v3 Fase 4 — Variantes *lite* y *full* · Plan de implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Objetivo:** publicar una variante *lite* (redes secuestradas, top atacantes y C2, unas 6.000 entradas) junto a la *full*, y dejar que cada router elija cuál usar al instalar. La elección se conserva al reinstalar.

**Arquitectura:**
- Cada fuente del catálogo declara en qué variantes entra.
- El generador normaliza y comprueba cada variante por separado y publica sus ficheros.
- El instalador lee la global `mblVariant` o, si no está, la variante ya instalada. La incrusta en `mbl-update`, que descarga `routeros-<variante>.txt` y rechaza una cabecera de otra variante.

**Tecnología:** Python 3.12 con la biblioteca estándar, scripting de RouterOS v7 y el harness e2e.

**Spec:** `docs/superpowers/specs/2026-10-21-mbl-v3-hardening-design.md`, fase 4 y §7.1, §7.2 y §7.7.

## Restricciones globales

- **Variantes:** `full` y `lite`. En `sources.toml`, cada fuente tiene `variants = ["full"]` o `["lite", "full"]`. Si se omite, vale `["full"]`. Toda fuente *lite* tiene que estar también en *full*.
- **Composición de *lite*** *(decisión del controlador, medida el 2026-10-21: unas 5.700 entradas)*: `spamhaus-drop`, `dshield`, `et-compromised`, `threatfox` y `threatcluster`.
- **Ficheros publicados:**

  | Variante | Para el router | Para otros firewalls |
  |---|---|---|
  | full | `routeros-full.txt` | `blocklist.txt` |
  | lite | `routeros-lite.txt` | `blocklist-lite.txt` |

  `blocklist.rsc` (legado de la v2) sigue siendo solo *full* y no cambia. Las cabeceras llevan `variant=full` o `variant=lite`.
- **Límites por variante:**
  - *full*: mínimo 5.000 y máximo 150.000 entradas.
  - *lite*: mínimo 1.000 y máximo 20.000.
  - En las dos, caída máxima del 50 % y crecimiento máximo de 2x. `--allow-growth` se aplica a ambas.
  - Sin un total previo de esa variante, no hay comprobación de caída ni de crecimiento.
  - Si **cualquier** variante falla, no se publica nada (código 1).
- **`stats.json`:**
  - se mantiene el `total` de primer nivel (= *full*) y `sources`;
  - se añade `"variants": {"full": {"total": N}, "lite": {"total": M}}`;
  - el total previo de cada variante se lee de `variants.<v>.total`; en *full*, si no está, se usa el `total` de primer nivel.
- **Router, tamaño mínimo de fichero:** *full* 100.000 bytes y *lite* 20.000. El mínimo de entradas es 1.000 en las dos.
- **Instalador:**
  1. Lee `:global mblVariant`. Valores válidos: `"full"` o `"lite"`; cualquier otro hace `:error` **antes de cambiar nada**.
  2. Si está vacía, usa la variante de la instalación existente, leída de la línea `:local variant "<v>"` del `mbl-update` instalado.
  3. Si no hay ninguna, usa `full`.
  4. Incrusta el valor con el marcador `@MBL_VARIANT@`.
  5. `mbl-update` descarga `$base . "/routeros-" . $variant . ".txt"`.
  6. Una cabecera con `variant=` distinto de la variante instalada da `bad header`.
- **Mensaje final:** `MBL: installed (script <v>, variant <var>)`. Se aplica igual al aviso "installed, but…".
- **Versión:** `3.2.0`, en `VERSION` y en el instalador.
- **Nada leído del fichero se ejecuta** (igual que en la fase 2).

## Puntos de revisión

1. **Reinstalar sin la global** en un router con *lite* mantiene *lite*. Lo cubre la Tarea 4: `test_14g_reinstall_keeps_lite`.
2. **Variante inválida** (`:global mblVariant "mini"`). El instalador falla sin tocar nada: las reglas y las listas quedan iguales. Lo cubre la Tarea 4: `test_14h_invalid_variant_rejected`.
3. **Cabecera de otra variante** (el router en *lite* recibe una cabecera *full*). Se rechaza con `bad header` y la lista activa no cambia. Lo cubre la Tarea 4: `test_14i_variant_mismatch_rejected`.
4. **La variante *lite* falla las comprobaciones pero la *full* no.** No se publica nada. Lo cubre la Tarea 2: `test_build_refuses_when_lite_fails`.
5. **Primera publicación con *lite*:** no existe `variants.lite.total` previo y no se aplica el tope de crecimiento. Lo cubre la Tarea 2: `test_first_lite_publish_skips_drop_and_growth`.

---

### Tarea 1: Catálogo con variantes

**Ficheros:**
- Modificar: `mbl/sources.py`, `sources.toml`
- Test: `tests/test_sources.py`

**Interfaces:**
- `Source` gana el campo `variants: tuple[str, ...] = ("full",)`. TOML devuelve una lista, que se convierte a tupla.
- Constante `VARIANTS = ("full", "lite")`.
- `load_sources` lanza `ValueError` si una variante es desconocida, si la lista está vacía o si una fuente es *lite* sin ser *full*.

- [ ] **Paso 1: tests que fallan.**
  - `test_variants_default_full`;
  - `test_unknown_variant_rejected`;
  - `test_lite_requires_full`;
  - `test_repo_catalog_lite_sources`: las fuentes *lite* del `sources.toml` real son exactamente las cinco de las restricciones globales.
- [ ] **Paso 2:** `python3 -m unittest tests.test_sources -v`. Esperado: FAIL.
- [ ] **Paso 3:** implementar. Añadir `variants = ["lite", "full"]` a las cinco fuentes.
- [ ] **Paso 4:** `python3 -m unittest discover`. Esperado: OK.
- [ ] **Paso 5:** commit: `feat(sources): per-source variants (lite/full)`.

### Tarea 2: Generador por variante

**Ficheros:**
- Modificar: `mbl/build.py`, `mbl/checks.py`, `mbl/render.py`
- Test: `tests/test_build.py`, `tests/test_checks.py`, `tests/test_render.py`

**Interfaces:**
- `checks.LIMITS = {"full": (5000, 150000), "lite": (1000, 20000)}`. `safety_errors(...)` mantiene su firma; `build` le pasa `min_total` y `max_total` por variante y antepone el nombre de la variante a cada error (`lite: …`).
- `render.write_outputs(out_dir, variants: dict[str, list[IPv4Network]], results, generated_at, script_version="0.0.0")`. La clave `"full"` es obligatoria.
  - Escribe `routeros-<v>.txt`; `blocklist.txt` para *full` y `blocklist-<v>.txt` para el resto.
  - Escribe `blocklist.rsc` solo para *full*.
  - Escribe `stats.json` con `variants`.
  - Los badges y `NOTICE.md` siguen como están; `NOTICE.md` añade una columna `variants`.
- `build` reparte los resultados por variante: la variante *v* recibe las redes de las fuentes que la incluyen. Normaliza cada variante y la comprueba.
- El e2e (`tests/e2e/test_routeros.py`) llama hoy a `write_outputs(out, networks, …)`. Se adapta a `{"full": networks}` en esta tarea, para que el `discover` siga en verde.

- [ ] **Paso 1: tests que fallan.**
  - `test_write_outputs_writes_both_variants`: existen `routeros-full.txt`, `routeros-lite.txt`, `blocklist.txt` y `blocklist-lite.txt`; la cabecera de lite dice `variant=lite`; `blocklist.rsc` contiene solo las redes de *full*.
  - `test_stats_variants`: `stats.json` tiene `total` = *full* y `variants.lite.total`.
  - `test_build_splits_by_variant`: un fetcher falso con una fuente lite+full y otra solo full; *lite* contiene solo la primera.
  - `test_build_refuses_when_lite_fails`: *lite* con 500 entradas (por debajo del mínimo de 1.000) y *full* bien; devuelve 1, no escribe nada y el error empieza por `lite:`.
  - `test_first_lite_publish_skips_drop_and_growth`: el `stats.json` previo no tiene `variants`; *lite* no se compara.
  - `test_previous_full_from_top_level_total`.
- [ ] **Paso 2:** ejecutar los tests. Esperado: FAIL.
- [ ] **Paso 3:** implementar. Adaptar la llamada de `tests/e2e/test_routeros.py` a `{"full": …}` y añadir la variante *lite* servida: 2.000 `/32` desde `46.0.0.0`.
- [ ] **Paso 4:** `python3 -m unittest discover`. Esperado: OK. Hacer un build real con las fuentes en vivo y comprobar que sale 0 y que *lite* está entre 1.000 y 20.000.
- [ ] **Paso 5:** commit: `feat(build): publish lite and full variants`.

### Tarea 3: Router — elegir variante y conservarla

**Ficheros:**
- Modificar: `routeros/install.rsc`, `VERSION` (`3.2.0`), `routeros/uninstall.rsc` (si hace falta)
- Test: `tests/test_installer_version.py` (añadir la comprobación del marcador `@MBL_VARIANT@`)

**Interfaces:**
- Produce el marcador `@MBL_VARIANT@` y la línea `:local variant "@MBL_VARIANT@"` en `mbl-update`.
- Produce la validación de la variante, según las restricciones globales, y el mensaje final con la variante.
- El `minSize` depende de la variante.

- [ ] **Paso 1:** test unitario: el marcador `@MBL_VARIANT@` aparece una sola vez en el cuerpo y hay una línea de inyección. Ejecutarlo. Esperado: FAIL.
- [ ] **Paso 2: implementar.**
  - Leer y validar la global.
  - Leer la variante instalada del `source` del `mbl-update` existente **antes** de borrarlo, con `:find` sobre el texto `:local variant "`.
  - Incrustar la variante, construir la URL por variante, aplicar el `minSize` por variante y comprobar `variant=` en la cabecera.
  - Subir `VERSION` y `mblScriptVersion` a `3.2.0`.
- [ ] **Paso 3:** `python3 -m unittest discover` en verde. Equilibrio de llaves: `0 0`.
- [ ] **Paso 4:** e2e local completo, con los casos actuales en verde. Los casos nuevos se añaden en la Tarea 4.
- [ ] **Paso 5:** commit: `feat(routeros): choose lite or full at install, keep it on reinstall`.

### Tarea 4: Casos e2e de variantes

**Ficheros:**
- Modificar: `tests/e2e/test_routeros.py`

**Casos** (antes de `test_15_final_uninstall`):
- `test_14f_install_lite`: `:global mblVariant "lite"` y luego `install`.
  - El servidor recibió `/routeros-lite.txt`.
  - La lista activa tiene exactamente el tamaño de la lista *lite* servida.
  - El log dice `variant lite`.
- `test_14g_reinstall_keeps_lite`: `:global mblVariant ""` y `install`. El servidor vuelve a recibir `/routeros-lite.txt` y sigue en *lite*.
- `test_14h_invalid_variant_rejected`: `:global mblVariant "mini"` y `install`.
  - La salida contiene el error.
  - Las 6 reglas `MBL:` siguen y la lista activa tiene el mismo número de entradas que antes.
  - Sigue instalado *lite*: el `source` de `mbl-update` contiene `routeros-lite.txt`.
- `test_14i_variant_mismatch_rejected`: con el router en *lite*, servir mediante `set_update_path` un fichero *lite* cuya cabecera diga `variant=full`. Se rechaza con `bad header` y la lista activa no cambia.
- `test_14j_back_to_full`: `:global mblVariant "full"` y `install`. El servidor recibe `/routeros-full.txt` y la lista activa tiene `LIST_SIZE` entradas.

  Este caso deja el router en *full* para el resto de la suite.

- [ ] **Paso 1:** escribir los casos.
- [ ] **Paso 2:** e2e local completo. Esperado: todo OK.
- [ ] **Paso 3:** commit: `test(e2e): lite/full variant cases`.

### Tarea 5: Documentación

**Ficheros:**
- Modificar: `README.md` (inglés y español), `CHANGELOG.md` (`3.2.0`), `docs/testing-chr.md`

- [ ] **Paso 1: README.**
  - **Elegir variante:** qué es *lite*, para quién es (poca RAM o solo bloqueo de C2), el comando con `:global mblVariant "lite";` delante del one-liner, que se conserva al reinstalar y cómo volver a *full*.
  - **Ficheros publicados:** añadir `routeros-lite.txt` y `blocklist-lite.txt`.
  - **Tabla de fuentes:** columna `lite`.
  - Lo mismo en la sección en español.
- [ ] **Paso 2: CHANGELOG `3.2.0`.** Los routers instalados con 3.1.0 verán el aviso de versión y pueden reinstalar.
- [ ] **Paso 3:** `docs/testing-chr.md`, con los casos 14f-14j.
- [ ] **Paso 4:** commit: `docs: lite and full variants`.
- [ ] **Paso 5: lo hace el controlador.** Push, PR, e2e en verde y merge. Comprobar que existe `lists/routeros-lite.txt` con `variant=lite` y que la cabecera dice `script=3.2.0`. Reinstalar el CHR del usuario: sigue en *full*.
