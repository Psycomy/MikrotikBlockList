# v3 Fase 3 — Aviso de versión nueva del script · Plan de implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Objetivo:** que un router avise en su log cuando hay una versión nueva del script MBL. El router **nunca se actualiza solo**.

**Arquitectura:**
- El instalador lleva incrustada su versión en `mbl-update`.
- La cabecera de `routeros-full.txt` ya publica `script=<VERSION>` (fase 2).
- Tras una carga correcta, `mbl-update` compara las dos versiones componente a componente. Si la publicada es mayor, escribe un aviso.
- Un test Python impide que `VERSION` y la versión incrustada en el instalador se desincronicen.
- Se crea `CHANGELOG.md`.

**Tecnología:** Python 3.12 con la biblioteca estándar, scripting de RouterOS v7 y el harness e2e.

**Spec:** `docs/superpowers/specs/2026-10-21-mbl-v3-hardening-design.md`, fase 3 y §7.10.

## Restricciones globales

- **Versión de esta fase: `3.1.0`.** Se pone en `VERSION` y en el instalador. La 3.0.0 fue la fase 2.
- **En `install.rsc`:** una línea `:local mblScriptVersion "3.1.0"` en el bloque de ajustes. Se incrusta en `mbl-update` igual que la URL, con el marcador `@MBL_VERSION@`.
- **Comparación:** numérica por componentes `MAJOR.MINOR.PATCH`.
  - `3.1.0 > 3.0.9` y `3.10.0 > 3.9.0`.
  - Si la publicada no tiene el formato `^[0-9]+\.[0-9]+\.[0-9]+$`, se ignora: no hay aviso ni error.
- **Texto exacto del aviso**, con nivel `warning`, una vez por cada actualización correcta:
  `MBL: script <publicada> available (installed <instalada>) - reinstall: /tool fetch url="https://raw.githubusercontent.com/Psycomy/MikrotikBlockList/main/routeros/install.rsc" check-certificate=yes; /import install.rsc`
- **El aviso no hace fallar nunca una carga.** Va dentro de `:do {} on-error={}`, después de `MBL: loaded …`, como el aviso de lista antigua.
- **Nada leído del fichero se ejecuta.** La versión publicada solo se usa como texto en el log y en la comparación numérica.
- **El router nunca se actualiza solo** *(decisión del usuario)*.

## Puntos de revisión

1. **Una versión publicada con basura** (`script=3.1.0;/system reboot`, `script=abc` o un valor vacío). No genera aviso ni rompe la carga. Lo cubre la Tarea 2: `test_17_bad_script_version_ignored`.
2. **Versión publicada igual o menor que la instalada.** No hay aviso. Lo cubre la Tarea 2: `test_16_no_notice_when_not_newer`.
3. **Comparación lexicográfica errónea** (`3.10.0` frente a `3.9.0`). Debe avisar. Lo cubre la Tarea 2: `test_18_numeric_comparison`.
4. **`VERSION` y el instalador desincronizados en un PR.** El CI falla. Lo cubre la Tarea 1: `test_installer_version_matches_VERSION`.
5. **El aviso aparece una vez por actualización,** no una vez por línea ni repetido. Lo cubre la Tarea 2: `test_15b_newer_script_notice`, que cuenta exactamente 1 línea tras la marca.

---

### Tarea 1: Versión incrustada, comparación y guardia de consistencia

**Ficheros:**
- Modificar: `VERSION` (`3.1.0`), `routeros/install.rsc`
- Test: `tests/test_installer_version.py` (nuevo, unitario, sin VM)

**Interfaces:**
- Produce `:local mblScriptVersion` en los ajustes del instalador y el marcador `@MBL_VERSION@` en `mbl-update`.
- Produce, dentro de `mbl-update`, una función local `mblVerGt do={…}` que recibe `$1` (publicada) y `$2` (instalada) y devuelve `true` o `false`.
- Produce el log exacto de las restricciones globales.
- La versión publicada se toma con el `mblField` existente sobre la cabecera, con la clave `script`.

- [ ] **Paso 1: test que falla.** `tests/test_installer_version.py`:
  - `test_installer_version_matches_VERSION`: lee `VERSION` (con strip) y busca en `routeros/install.rsc` la línea `:local mblScriptVersion "<v>"`; tienen que coincidir.
  - `test_installer_has_version_placeholder`: el texto `@MBL_VERSION@` aparece exactamente una vez dentro del cuerpo de `mbl-update`.
- [ ] **Paso 2:** `python3 -m unittest tests.test_installer_version -v`. Esperado: FAIL.
- [ ] **Paso 3: implementar.**
  - Subir `VERSION` a `3.1.0`.
  - Añadir la línea de ajustes y el marcador, e incrustar la versión igual que se hace con `@MBL_URL@`.
  - Guardar la versión publicada al leer la cabecera.
  - Escribir `mblVerGt`, sin `:parse` y con `:tonum` por componente.
  - Poner el bloque del aviso después del aviso de lista antigua.
- [ ] **Paso 4:** `python3 -m unittest discover` en verde. Comprobación de equilibrio de llaves de `install.rsc`. Esperado: `0 0`.
- [ ] **Paso 5:** commit: `feat(routeros): warn when a newer MBL script is published`.

### Tarea 2: Casos e2e del aviso

**Ficheros:**
- Modificar: `tests/e2e/test_routeros.py`

**Interfaces:**
- Consume el texto del aviso (restricciones globales) y `write_outputs(..., script_version=…)` (fase 2) para generar variantes de la lista servida.

**Casos** (antes de `test_15_final_uninstall`, que pasa a ser el último; renumerar si hace falta):
- `test_15b_newer_script_notice`: servir una lista con `script=9.0.0`. Tras `mbl-update`, hay exactamente **una** línea `warning` tras la marca que contiene `MBL: script 9.0.0 available (installed 3.1.0) - reinstall: /tool fetch url="https://raw.githubusercontent.com/Psycomy/MikrotikBlockList/main/routeros/install.rsc"`. La carga es correcta.
- `test_16_no_notice_when_not_newer`: con `script=3.1.0` y `script=3.0.5`, no hay ninguna línea `MBL: script` tras la marca.
- `test_17_bad_script_version_ignored`: con `script=3.1.0;/system/reboot` (sin espacios, para que siga siendo un solo token), `script=abc` y `script=` vacío:
  - no hay aviso;
  - la carga es correcta;
  - el router no se reinicia (la global `mblE2eAlive` sobrevive, como en test_11).
- `test_18_numeric_comparison`: con `script=3.10.0` frente a la instalada `3.1.0`, avisa.

- [ ] **Paso 1:** escribir los casos. La versión instalada se lee de `VERSION`, no se pone a mano.
- [ ] **Paso 2: ejecución real local.** `MBL_E2E=1 MBL_E2E_CACHE=<cache> python3 -m unittest tests.e2e.test_routeros -v`. Esperado: todo OK.
- [ ] **Paso 3:** commit: `test(e2e): newer-script notice cases`.

### Tarea 3: CHANGELOG y documentación

**Ficheros:**
- Crear: `CHANGELOG.md`
- Modificar: `README.md` (inglés y español), `docs/testing-chr.md`

- [ ] **Paso 1:** `CHANGELOG.md`, en formato *Keep a Changelog* y en inglés, con estas entradas:
  - `3.1.0` (2026-10-21): aviso de versión nueva.
  - `3.0.0` (2026-10-21): ingesta segura sin `/import`, `routeros-full.txt`, CI e2e en CHR, `mblUrlBase` y el paso de v2 a v3.
  - `2.0.0` (2026-10-19): la reescritura v2 (resumen breve).
- [ ] **Paso 2: README.**
  - Una sección "Updates" o "Actualizaciones": qué significa el aviso `MBL: script … available`, que basta con volver a ejecutar el comando de instalación y que el router nunca se actualiza solo.
  - Enlace a `CHANGELOG.md`.
- [ ] **Paso 3:** `docs/testing-chr.md`: añadir los casos 15b-18.
- [ ] **Paso 4:** commit: `docs: changelog and update notice`.
- [ ] **Paso 5: lo hace el controlador.** Push, PR, e2e en verde, merge, comprobación de la publicación (`script=3.1.0` en la cabecera) y reinstalación en el CHR del usuario.
