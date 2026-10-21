# v3 Fase 1 — Pruebas end-to-end de RouterOS en el CI · Plan de implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Objetivo:** que cada cambio en los scripts del router se pruebe solo, arrancando un CHR v7 real en QEMU, tanto en GitHub Actions como en local.

**Arquitectura:**
- Un *harness* Python en `tests/e2e/` arranca un CHR desde una imagen fijada, lo prepara por consola serie (contraseña de prueba y clave SSH) y ejecuta comandos por SSH.
- Un servidor HTTPS de prueba, con una CA propia generada al vuelo, sirve una lista generada por `mbl build`.
- El instalador publicado gana una global opcional `mblUrlBase`, para que las pruebas usen el instalador **idéntico** al que se publica, apuntado al servidor de prueba.
- Los casos de prueba son `unittest` que solo corren con `MBL_E2E=1`.
- Un workflow nuevo los lanza en los PR que tocan el router, cada semana contra la última estable y a mano.

**Tecnología:** Python 3.12 con la biblioteca estándar en el harness (y `subprocess` para `qemu-system-x86_64`, `ssh`, `scp` y `openssl`), QEMU/KVM, GitHub Actions y scripting de RouterOS v7.

**Spec:** `docs/superpowers/specs/2026-10-21-mbl-v3-hardening-design.md` (fase 1 y §7.3, §7.4, §7.5).

## Restricciones globales

- **El generador** (`mbl/`) sigue siendo solo biblioteca estándar. **El harness** (`tests/e2e/`) puede usar herramientas del sistema (`qemu-system-x86_64`, `qemu-img`, `ssh`, `scp`, `openssl`, `unzip`), pero no paquetes de PyPI.
- **Los tests e2e nunca corren en `python -m unittest discover` normal.** Toda la clase se salta salvo que `MBL_E2E=1`, porque `build.yml` ejecuta `discover` en cada push.
- **CHR fijado:** versión `7.24.5`, imagen `https://download.mikrotik.com/routeros/7.24.5/chr-7.24.5.img.zip`. El checksum SHA-256 va en `tests/e2e/chr-version.txt`, calculado una vez al descargarla.
- **Canal de la última estable:** `https://upgrade.mikrotik.com/routeros/NEWESTa7.stable`. La primera palabra del contenido es la versión.
- **El instalador probado es el fichero `routeros/install.rsc` sin modificar.** Solo se ponen globales antes (`:global mblUrlBase "https://10.0.2.2:8443"`).
- **Todo HTTPS sigue con `check-certificate=yes`.** En el CHR de prueba se importa como *trusted* la CA de prueba. Esa CA **solo existe en el entorno de pruebas**.
- **Instalación limpia:** reglas `MBL:`, los schedulers `mbl-daily` y `mbl-boot` y ≥1000 entradas cargadas. El instalador actual crea **6** reglas raw.
- **Ruta de gestión.** En QEMU, la red de usuario reenvía el SSH (`hostfwd=tcp:127.0.0.1:<puerto>-:22`) y el host se ve desde el CHR como `10.0.2.2`. `ether1` es WAN. La LAN es un bridge vacío `bridge-lan` y las listas `WAN`/`LAN` se crean en la preparación, como en `docs/testing-chr.md`.
- **Modo "host existente".** Con `MBL_E2E_SSH=admin@192.168.33.118` (y opcionalmente `MBL_E2E_KEY`), el harness no arranca QEMU y usa ese CHR por clave SSH. **Nunca usa contraseña** contra un host que no ha arrancado él mismo.

## Puntos de revisión

1. **KVM no disponible o el CHR no arranca.** El harness falla con un mensaje claro al cabo de un tiempo límite (arranque ≤ 180 s, SSH ≤ 120 s), sin colgarse. Lo cubre la Tarea 2: `test_boot_timeout_raises` (con un binario falso de QEMU).
2. **Una prueba falla a mitad de camino.** La VM y el servidor HTTPS se paran siempre (`tearDownClass` y `atexit`), sin dejar procesos `qemu` vivos en el runner ni en local. Lo cubre la Tarea 2: `test_stop_is_idempotent`.
3. **`mblUrlBase` no definida.** El instalador se comporta exactamente como hoy y usa la URL de `lists`. Lo cubre la Tarea 1: comprobación textual y caso e2e `test_09_default_url_without_override` (Tarea 3).
4. **Puerto ocupado** para el reenvío SSH o para el servidor HTTPS. Se elige un puerto libre al vuelo. Lo cubre la Tarea 2: `test_free_port`.
5. **El `discover` normal descubre `tests/e2e`.** Debe quedar saltado sin errores aunque falten QEMU u openssl. Lo cubre la Tarea 3: `test_e2e_skipped_without_flag`.

---

### Tarea 1: Override `mblUrlBase` en el instalador

**Ficheros:**
- Modificar: `routeros/install.rsc` (bloque *settings*, líneas ~15-21)
- Modificar: `README.md` (sección *Forks*, nota para desarrolladores, en inglés y en español)

**Interfaces:**
- Produce: la global opcional `mblUrlBase`.
  - **Vacía o no definida:** `mblUrl` queda como hoy.
  - **Definida:** `mblUrl = $mblUrlBase . "/blocklist.rsc"`.
  - El valor se incrusta en `mbl-update` (vía `@MBL_URL@`) como hasta ahora, así que las actualizaciones siguientes usan la misma base.

- [ ] **Paso 1:** justo después de `:local mblUrl "..."`, añadir `:global mblUrlBase` y `:if ([:len $mblUrlBase] > 0) do={ :set mblUrl ($mblUrlBase . "/blocklist.rsc") }`. Con un comentario: `# Test/dev only: set :global mblUrlBase before /import to use another server.`
- [ ] **Paso 2:** comprobar que el fichero sigue equilibrado. Ejecutar `python3 -c "s=open('routeros/install.rsc').read(); print(s.count('{')-s.count('}'), s.count('[')-s.count(']'))"`. Esperado: `0 0`.
- [ ] **Paso 3:** README. En *Forks*, una línea: para probar contra otro servidor, `:global mblUrlBase "https://host:port"` antes del `/import`. Lo mismo, una línea, en la sección en español.
- [ ] **Paso 4:** commit: `feat(routeros): optional mblUrlBase override for testing`.

  La validación real está en la Tarea 3, casos `test_01_clean_install` y `test_09_default_url_without_override`.

### Tarea 2: Harness CHR y servidor HTTPS de prueba

**Ficheros:**
- Crear: `tests/e2e/__init__.py` (vacío)
- Crear: `tests/e2e/chr-version.txt` (`7.24.5 <sha256>`)
- Crear: `tests/e2e/harness.py`
- Test: `tests/e2e/test_harness.py`, unitario y sin VM, que corre en el `discover` normal

**Interfaces (producidas):**
- `free_port() -> int`.
- `class TlsServer(root: Path)`: genera en un directorio temporal una CA (`ca.crt`/`ca.key`) y un certificado de servidor para `IP:10.0.2.2` e `IP:127.0.0.1` firmado por esa CA, con `openssl` y SAN. Sirve `root` por HTTPS en `0.0.0.0:<free_port>` desde un hilo. Tiene:
  - las propiedades `port: int` y `ca_pem: Path`;
  - los métodos `start()` y `stop()`, este último idempotente;
  - un modo `fail_paths: set[str]` que devuelve 404 para esas rutas.
- `class Chr`, con dos constructores:
  - `Chr.boot(image: Path, workdir: Path, boot_timeout=180, ssh_timeout=120) -> Chr`: copia la imagen a `workdir` y arranca `qemu-system-x86_64 -enable-kvm -m 256 -smp 1 -nographic -serial unix:<sock>,server,nowait -nic user,model=virtio,hostfwd=tcp:127.0.0.1:<p>-:22` con el disco como `virtio`. Por la consola serie entra como `admin` sin contraseña, fija una contraseña de prueba aleatoria (contesta al aviso de cambio obligatorio si aparece) y deja una clave SSH ed25519 generada en `workdir`: la sube y la importa con `/user ssh-keys import`. Después aplica la configuración base de la restricción "Ruta de gestión".
  - `Chr.existing(ssh: str, key: Path | None) -> Chr`: usa un CHR ya creado, solo por clave.
- Métodos de `Chr`:
  - `run(cmd: str, timeout=120) -> str`: un comando RouterOS por SSH con `BatchMode`, devuelve stdout y lanza `ChrError` si el código no es 0;
  - `upload(local: Path, name: str)`;
  - `reboot(wait=True)`: hace `:execute {/system reboot}` y espera a que vuelva el SSH;
  - `stop()`: idempotente, mata QEMU, también vía `atexit`.
- `ensure_image(version: str, sha256: str | None, cache: Path) -> Path`: descarga y descomprime la imagen. Si se da `sha256`, lo verifica y lanza `ChrError` si no coincide.
- `latest_stable() -> str`: lee el canal NEWESTa7.stable.
- `class ChrError(Exception)`.

- [ ] **Paso 1: tests que fallan.** En `tests/e2e/test_harness.py`, sin VM:
  - `test_free_port`: dos llamadas devuelven puertos enteros entre 1024 y 65535 a los que se puede hacer *bind*.
  - `test_tls_server_serves_with_ca`: se salta si no hay `openssl`. Sirve un fichero con contenido `hello`. `urllib` con `ssl.create_default_context(cafile=ca_pem)` contra `https://127.0.0.1:<port>/x.txt` devuelve `hello`, y un `fail_paths={"/missing"}` da HTTPError 404.
  - `test_ensure_image_checksum_mismatch`: con una "descarga" falsa (un `file://` a un zip temporal que contiene `chr-test.img`) y un sha256 erróneo, lanza `ChrError`.
  - `test_boot_timeout_raises`: con `qemu-system-x86_64` sustituido por un script que solo duerme (`PATH` temporal) y `boot_timeout=2`, `Chr.boot` lanza `ChrError` en menos de 10 s y no deja el proceso vivo.
  - `test_stop_is_idempotent`: `stop()` dos veces sobre el Chr del caso anterior no lanza nada.
- [ ] **Paso 2:** `python3 -m unittest tests.e2e.test_harness -v`. Esperado: FAIL (ImportError).
- [ ] **Paso 3:** implementar `tests/e2e/harness.py`. La consola serie se maneja con `socket` (AF_UNIX) y una función `_expect(sock, pattern: bytes, timeout) -> bytes` hecha a mano: sin pexpect.
- [ ] **Paso 4:** descargar una vez la imagen 7.24.5 y escribir su sha256 en `chr-version.txt`. Los tests unitarios: PASS.
- [ ] **Paso 5: prueba manual en local** (este equipo tiene `/dev/kvm`). Ejecutar `python3 -c "from tests.e2e.harness import *; ..."`, que arranca, hace `run(':put [/system resource get version]')` y para. Esperado: `7.24.5 (stable)`. Pegar la salida en el informe.
- [ ] **Paso 6:** commit: `test(e2e): CHR harness and TLS test server`.

### Tarea 3: Casos de prueba end-to-end

**Ficheros:**
- Crear: `tests/e2e/test_routeros.py`
- Test: el propio fichero, más `test_e2e_skipped_without_flag` en `tests/e2e/test_harness.py`

**Interfaces:**
- Consume: todo lo de la Tarea 2 y `mbl.render.write_outputs(out_dir, networks, results, generated_at)`, además del `routeros/install.rsc` y el `uninstall.rsc` del repo, sin modificar.
- `setUpClass`:
  1. Si `MBL_E2E` no es `1`, lanza `SkipTest`.
  2. Genera **siempre** una lista sintética y determinista. Se usa `mbl.render.write_outputs` con 5.000 redes `/32` consecutivas desde `45.0.0.0` (globales, así que pasan las mismas validaciones que la real) y `results=[]`. No se usan las fuentes reales: el CI no debe depender de su disponibilidad.
  3. Copia el resultado a `served/` junto a `blocklist-truncated.rsc` (el mismo sin las 2 últimas líneas) y arranca `TlsServer`.
  4. Arranca el CHR (`Chr.boot` o `Chr.existing` según `MBL_E2E_SSH`), sube `ca.crt` y lo importa con `/certificate import file-name=ca.crt trusted=yes`.
  5. Sube `install.rsc` y `uninstall.rsc`.
- Helpers del test:
  - `install(base: str | None)`: si hay base, ejecuta `:global mblUrlBase "<base>"` y luego `/import install.rsc`.
  - `active_list() -> str`: la lista a la que apunta la regla `MBL: in`.
  - `count(list) -> int`.
  - `log() -> str`.

**Casos** (métodos, en este orden, con `unittest` ordenado por nombre `test_01_…`):
- `test_01_clean_install`: tras `install(base)`, hay 6 reglas raw con comentario `^MBL:`, los schedulers `mbl-daily` y `mbl-boot` existen, `count(active_list()) >= 1000` y el log contiene `MBL: installed`.
- `test_02_update_alternates`: `/system script run mbl-update` hace que la lista activa cambie (`mbl-a` ↔ `mbl-b`), que la antigua quede vacía y que la nueva tenga ≥1000 entradas.
- `test_03_truncated_keeps_active`: con el `url` de `mbl-update` cambiado a `…/blocklist-truncated.rsc` (`/system script set mbl-update source=` con el reemplazo hecho en el router), al ejecutar `mbl-update` la lista activa y su número de entradas no cambian y el log tiene una línea de error `MBL:`. Al final se restaura el `url`.
- `test_04_dead_url_keeps_active`: igual, pero con `fail_paths` sobre la ruta real (404).
- `test_05_reboot_reloads`: `reboot()` y luego esperar a que en el log aparezca `MBL: loaded` con hora posterior al arranque, como máximo 150 s. La lista activa tiene ≥1000 entradas.
- `test_06_flash_path`: `/file add type=directory name=flash`, luego `mbl-update`. Existe `flash/mbl-last.rsc`, un `mbl-update` en modo arranque (`:global mblBoot true`) carga desde ella y al final se borra el directorio `flash`.
- `test_07_reinstall_no_duplicates`: un segundo `install(base)` deja exactamente 6 reglas `MBL:` y 2 schedulers, mantiene las entradas `MBL: admin` de `mbl-allow` y la lista activa no se vacía.
- `test_08_uninstall_clean`: `/import uninstall.rsc` deja 0 reglas `MBL:`, 0 scripts y schedulers `mbl-*`, `mbl-a` y `mbl-b` vacías y ningún fichero `mbl-*.rsc`. Lo que no es MBL (las listas `WAN`/`LAN`) sigue intacto.
- `test_09_default_url_without_override`: tras `:global mblUrlBase ""` e `install(None)`, el `source` de `mbl-update` contiene `https://raw.githubusercontent.com/Psycomy/MikrotikBlockList/lists/blocklist.rsc`. Al terminar, desinstala.

- [ ] **Paso 1:** escribir `test_e2e_skipped_without_flag` en `test_harness.py`. Ejecuta `python3 -m unittest tests.e2e.test_routeros` con `MBL_E2E` borrado y comprueba que la salida contiene `skipped` y el código es 0. Ejecutarlo. Esperado: FAIL, porque el módulo no existe.
- [ ] **Paso 2:** escribir `tests/e2e/test_routeros.py` con los 9 casos.
- [ ] **Paso 3:** `python3 -m unittest discover -v` (sin la variable). Esperado: todo OK y los e2e *skipped*.
- [ ] **Paso 4: ejecución real en local.** `MBL_E2E=1 python3 -m unittest tests.e2e.test_routeros -v`. Esperado: 9/9 OK. Si alguno falla por un defecto del **instalador**, no se arregla en esta tarea: se anota en el informe y se para (fase 1 = solo pruebas, más el override de la Tarea 1).
- [ ] **Paso 5: ejecución real contra el CHR del usuario** (`MBL_E2E_SSH=admin@192.168.33.118 MBL_E2E_KEY=~/.ssh/antonio`), si responde. Esperado: 9/9 OK. Si no responde, se anota "no ejecutado" y no es un fallo.
- [ ] **Paso 6:** commit: `test(e2e): RouterOS install/update/reboot/uninstall cases`.

### Tarea 4: Workflow y documentación

**Ficheros:**
- Crear: `.github/workflows/routeros-e2e.yml`
- Modificar: `docs/testing-chr.md` (nueva sección "Pruebas automáticas (CI)")
- Modificar: `README.md` (badge del workflow e2e junto al de build; una línea en la sección de pruebas)

**Contenido decidido del workflow:**
- **Disparadores:**
  - `pull_request` con `paths: [routeros/**, mbl/render.py, tests/e2e/**, .github/workflows/routeros-e2e.yml]`;
  - `schedule: cron "41 5 * * 1"` (lunes);
  - `workflow_dispatch` con el input `chr_version` (texto, vacío = fijada).
- **Job `e2e`:** `runs-on: ubuntu-latest`, `timeout-minutes: 30`, `permissions: contents: read`. Pasos:
  1. Checkout (`actions/checkout@v7`) y `setup-python@v7` (3.12).
  2. Activar KVM con la regla udev habitual para dar acceso a `/dev/kvm` al usuario del runner, y comprobar `ls -l /dev/kvm`.
  3. `sudo apt-get install -y qemu-system-x86 qemu-utils openssl unzip`.
  4. Resolver la versión:
     - en `schedule`, con `latest_stable()` y sin checksum (se registra el sha256 calculado en el *summary*);
     - en `workflow_dispatch` con input, ese valor;
     - en otro caso, `chr-version.txt` con su checksum.
  5. Caché de la imagen con `actions/cache@v5`, clave `chr-<versión>`.
  6. `MBL_E2E=1 python -m unittest tests.e2e.test_routeros -v`.
  7. Si falla, subir como artefacto (`actions/upload-artifact`) el log de consola serie y `/log print` del CHR.

- [ ] **Paso 1:** escribir el workflow. Validarlo con `npx --yes @action-validator/cli .github/workflows/routeros-e2e.yml`. Esperado: salida vacía, código 0.
- [ ] **Paso 2:** documentación:
  - `docs/testing-chr.md`: cómo ejecutar en local (`MBL_E2E=1 …`), contra el CHR de Proxmox (`MBL_E2E_SSH=…`), qué cubre cada caso y cómo subir la versión fijada.
  - README: badge y una línea.
- [ ] **Paso 3:** commit: `ci: RouterOS end-to-end tests on CHR`.
- [ ] **Paso 4:** push de la rama y PR contra `main`. Esperado: el job `e2e` arranca en el PR (toca `routeros/` y el workflow) y termina en verde. Si falla en el runner y en local no, se analiza con los artefactos y se corrige en esta tarea.
- [ ] **Paso 5:** lanzar a mano `gh workflow run routeros-e2e.yml -f chr_version=<la última estable>` sobre la rama. Esperado: verde, o un fallo que se documenta en el PR si es una regresión de RouterOS.
