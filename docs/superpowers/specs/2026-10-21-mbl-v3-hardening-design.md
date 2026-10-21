# MikrotikBlockList v3 — Seguridad, pruebas automáticas, variantes e IPv6

Fecha: 2026-10-21 · Repo: `Psycomy/MikrotikBlockList` · Parte de la v2 (spec `2026-10-19-mikrotik-blocklist-v2-design.md`), ya publicada y en uso.

## 1. Intención

La v2 funciona y está publicada. Esta versión cierra los huecos que quedan:

- **El riesgo grave.** El router ejecuta con `/import` un fichero descargado de GitHub. Si alguien compromete la cuenta o el workflow, podría ejecutar comandos en todos los routers instalados.
- **Las pruebas manuales.** Los scripts del router solo se prueban a mano, en el CHR del usuario.
- **Más usuarios.** El proyecto es público, así que también se piensa en quien tenga equipos pequeños o IPv6.

El equipo de referencia del usuario es un **hAP ax3** (1 GB de RAM, sin carpeta `flash/`), solo con IPv4. IPv6 y la variante *lite* son **pensando en otros usuarios**.

## 2. Fases

Se hacen **en este orden**, cada una en su propio PR, integrado y probado en el CHR antes de empezar la siguiente:

1. Pruebas del router en el CI.
2. Ingesta sin `/import`.
3. Aviso de versión nueva del script.
4. Variantes *lite* y *full*.
5. IPv6.
6. Mejoras menores.

## 3. Objetivos por fase

### Fase 1 — Pruebas end-to-end de RouterOS en el CI

- Un job de GitHub Actions arranca un **CHR v7** en QEMU con KVM: la misma versión estable que el CHR de pruebas (7.24.5), con una imagen fijada por versión y checksum.
- Sobre ese CHR instala con el instalador del repo y comprueba lo siguiente:
  - instalación limpia: reglas, schedulers y ≥1000 entradas cargadas;
  - una actualización que alterna `mbl-a` y `mbl-b`;
  - un fichero truncado y una URL caída, que dejan la lista activa intacta;
  - un reinicio, con recarga desde la copia de arranque;
  - una reinstalación sin duplicados;
  - la desinstalación, que deja todo limpio.
- La lista se sirve desde el propio runner, con una lista generada en ese job, para no depender de la rama `lists` (ver §7.4).
- Debe funcionar con `check-certificate=yes`. El cómo lo decide el builder: CA de prueba importada en el CHR o un mecanismo equivalente que **solo** exista en el entorno de pruebas. La URL de pruebas se inyecta sin cambiar el comportamiento del instalador publicado.
- **Cuándo corre:** en cada PR que toque `routeros/`, `mbl/render.py` o el workflow, y una vez por semana (cron) contra la última imagen CHR estable fijada.
- **Requisito:** la fase 1 se integra **antes** que cualquier otro cambio en `routeros/`.

### Fase 2 — Ingesta segura, sin `/import`

- La Action publica además una lista en **texto plano** con una entrada por línea, una cabecera y un pie:
  ```
  # MikrotikBlockList v3 format=1 variant=full family=ipv4 generated=<ISO8601Z> entries=<N> script=<versión>
  1.2.3.0/24
  4.5.6.7
  ...
  # MBL-END entries=<N>
  ```
- El script del router:
  1. lee el fichero por trozos con `/file read` (disponible en v7 ≥ 7.13; el mínimo sigue siendo 7.21);
  2. **valida cada línea** como IPv4 o CIDR (`:toip` y comprobación de prefijo 8-32) y la añade con `add list=$target address=$a timeout=7d`;
  3. descarta las líneas que no validan, contándolas;
  4. rechaza la carga, sin tocar la lista activa, si falta la cabecera o el pie, si `entries` no coincide con lo añadido o si hay más de un 1 % de líneas inválidas.
- **Ningún contenido del fichero se ejecuta.** Cada línea se trata solo como dato.
- **Compatibilidad:** `blocklist.rsc` se sigue publicando sin cambios para los routers ya instalados con la v2. Seguirá así **al menos hasta 2027-04-30**, y el README indica cómo pasar a la v3: reinstalar con el mismo comando.
- **Rendimiento:**
  - **Objetivo:** actualización completa de la lista *full* en ≤ 5 min en el CHR de 1 vCPU y ≤ 2 min en un hAP ax3. Se mide y se anota en `docs/testing-chr.md`.
  - **Si no se cumple en el CHR,** el builder optimiza: trozos más grandes, menos llamadas o similar. **No** vuelve a `/import`. Si aun así no llega, para y lo consulta.
- Se mantienen todas las garantías de la v2:
  - listas alternas;
  - copia de arranque `mbl-last` (ahora del `.txt`);
  - lock;
  - la lista activa nunca queda vacía;
  - prefijo `flash/` cuando exista.

### Fase 3 — Aviso de versión nueva del script

- Fichero `VERSION` en `main` con el formato `3.0.0`. El instalador incrusta su versión en el script `mbl-update`.
- La cabecera de la lista publicada lleva `script=<versión>`, leída de `VERSION` por la Action.
- Si la versión publicada es mayor que la instalada, `mbl-update` escribe en el log, con nivel *warning*, una vez por actualización:
  `MBL: script <publicada> available (installed <instalada>) - reinstall: <comando del README>`
- **El router nunca se actualiza solo** *(decisión del usuario)*.
- `CHANGELOG.md` con una entrada por versión. Se crea aquí y se alimenta en las fases siguientes.

### Fase 4 — Variantes *lite* y *full*

- Cada fuente de `sources.toml` gana el campo `variants`, con valores `["full"]` o `["lite", "full"]`.
- **Lite** = Spamhaus DROP + DShield + ThreatFox + ThreatCluster + ET compromised: redes secuestradas, top atacantes y C2. Hoy son unas 6.000 entradas. La composición exacta la decide el builder midiendo, con un objetivo de ≤ 10.000 entradas.
- **Full** = el catálogo completo actual.
- **Ficheros publicados:** `blocklist.txt` (full) y `blocklist-lite.txt`. Las comprobaciones de seguridad van por variante; la mínima de *lite* es 1.000 entradas.
- **Instalador:** variable `mblVariant` al principio, con valor por defecto `"full"`.
- El README explica cuándo elegir *lite*: equipos con poca RAM, o quien solo quiera cortar conexiones a C2.

### Fase 5 — IPv6 (opcional, desactivado por defecto)

- **Generador:**
  - acepta entradas IPv6 en los parsers, que hoy las descartan;
  - añade Spamhaus `drop_v6.txt` como fuente IPv6;
  - normaliza con equivalentes IPv6: fuera los rangos no globales, ULA, link-local, documentación y multicast, y todo lo más amplio que /19 (el builder confirma ese umbral con los datos de Spamhaus v6);
  - aplica una allowlist IPv6: rangos IPv6 de Cloudflare, del CDN de GitHub (Fastly) y de los DNS públicos.
- **Publica** `blocklist6.txt` y `blocklist6-lite.txt`, con las mismas comprobaciones de seguridad y mínimos propios. Si hoy salen muy pocas entradas, el mínimo lo calibra el builder con datos reales.
- **Router:**
  - variable `mblIpv6 false` por defecto;
  - con `true` crea `mbl6-a` y `mbl6-b`, `mbl6-allow` y las reglas equivalentes en `/ipv6 firewall raw`, con la misma lógica de alternancia, copia de arranque y validación (`:toip6`);
  - con `false` **no crea nada** de IPv6, y la desinstalación limpia ambos casos.
- **Pruebas:** el CI y el CHR del usuario las ejecutan con IPv6 activado en la VM.

### Fase 6 — Mejoras menores

- **Plantilla de issue** "Falso positivo" (IP, fuente si se conoce, qué se rompió) y plantilla "Bug".
- **Allowlist automática de CDN.**
  - En cada build, la Action descarga los rangos de Fastly (`api.fastly.com/public-ip-list`) y CloudFront (`ip-ranges.amazonaws.com`, servicio CLOUDFRONT), y la lista de Cloudflare (sustituye a la copia manual). Con eso, sin el rango de GitHub ni los DNS, que siguen fijos en `allowlist.txt`.
  - Si una de esas descargas falla, se usa la última copia guardada en `allowlist-cdn.snapshot.txt` del repo, y el build no se cae.
- **Endurecimiento de la cuenta y el repo.** `docs/security.md` con los pasos:
  - 2FA en la cuenta;
  - protección de `main` (PR obligatorio y CI en verde);
  - restringir quién puede lanzar workflows;
  - revisar los tokens.

  **Los cambios de configuración de GitHub los hace el usuario o los autoriza uno a uno.** No se aplican sin pedirlo.
- **CHANGELOG** al día (creado en la fase 3).

## 4. No objetivos

- Que el router se actualice solo (decisión del usuario).
- Firmar criptográficamente la lista: RouterOS no tiene primitivas para verificar firmas desde un script. La defensa es no ejecutar nada (fase 2) y endurecer la cuenta (fase 6).
- RouterOS v6, bloqueo por DNS o dominios, uso comercial.
- Sumarización con pérdidas (bloquear /24 enteros). Ya se estudió y se descartó por ahora.

## 5. Anti-objetivos

- **Romper los routers ya instalados con la v2:** `blocklist.rsc` sigue publicándose (fase 2).
- Dejar la lista activa vacía o cortar el acceso al admin, en cualquier fase.
- Crear reglas IPv6 en un router que no lo ha pedido.
- Que un fallo de una descarga auxiliar (CDN, versión) impida publicar la lista.
- Que el router ejecute contenido descargado.

## 6. Restricciones

- Python 3.12 solo con la biblioteca estándar. Mismo estilo y estructura que el paquete `mbl/` actual.
- RouterOS ≥ 7.21. Lo probado es 7.24.5 en CHR, y el hAP ax3 del usuario como hardware real cuando esté disponible.
- Los tests Python existentes siguen en verde. Cada fase añade los suyos con TDD.
- El CHR del usuario (`192.168.33.118`, acceso solo por clave SSH, `ether1` es la ruta de gestión) se usa para la validación manual de cada fase. Puede estar apagado: si no responde, se pide al usuario que lo encienda.

## 7. Decisiones tomadas tras la revisión del diseño *(decisiones mías)*

1. **Elegir variante e IPv6 sin editar el fichero.** Se hace con variables globales puestas antes del comando de instalación de una línea. Si no se ponen, se usan los valores por defecto (`full`, `false`):
   ```
   :global mblVariant "lite"; :global mblIpv6 true; /tool fetch url=".../install.rsc" check-certificate=yes; /import install.rsc
   ```
   **Al reinstalar se conserva la configuración existente.** El instalador lee la variante y el IPv6 guardados en la instalación anterior, salvo que las globales digan otra cosa. Así, el comando que sugiere el aviso de la fase 3 nunca devuelve a nadie a `full` sin IPv6.
2. **Los ficheros planos para otros firewalls quedan sin tocar.** `blocklist.txt` (y `blocklist-lite.txt`, `blocklist6.txt`, `blocklist6-lite.txt`) son una entrada por línea, sin cabecera. El router usa ficheros aparte, con cabecera y pie: `routeros-full.txt`, `routeros-lite.txt`, `routeros6-full.txt` y `routeros6-lite.txt`.
3. **Versión del CHR en el CI.**
   - Los PR usan la imagen fijada: versión más checksum.
   - El cron semanal descubre la última estable desde el canal oficial de actualizaciones de MikroTik y prueba con ella.
   - Si falla, el job se pone en rojo y GitHub avisa por correo al dueño. Subir la versión fijada es un cambio manual en un PR.
4. **URL de pruebas.** El instalador admite una global opcional `mblUrlBase` que sustituye la base de las URLs. Se añade **dentro de la fase 1** como parte de habilitar las pruebas. El CI ejecuta el instalador **byte a byte idéntico** al publicado y solo pone esa global antes.
5. **`flash/` en el CI.** Hay un caso de prueba que crea un directorio `flash` en el CHR para cubrir esa ruta, como se hizo en la v2. Queda pendiente validarlo en hardware real con `flash/`.
6. **Paso de v2 a v3.**
   - Antes de la fase 2 se crea la etiqueta `v2.0.0` sobre el `main` actual.
   - El CI incluye una prueba de actualización: instalar con el `install.rsc` de esa etiqueta y reinstalar con el de la v3.
   - El instalador v3 mantiene pobladas las listas mientras repunta las reglas.
   - El `mbl-last.rsc` antiguo se borra solo después de la primera carga v3 correcta.
7. **Límites por variante.**
   - *lite*: mínimo 1.000 y máximo 20.000.
   - IPv6: mínimo calibrado con datos reales, por defecto 50.
   - Caída máxima del 50 % y crecimiento máximo de 2x, igual que hoy.
   - Si una variante no tiene estadísticas previas (primera publicación), no se aplican las comprobaciones de caída ni de crecimiento.
   - `stats.json` gana una sección `variants` y conserva el `total` de primer nivel (= full IPv4), por compatibilidad con el workflow ya desplegado.
8. **IPv6 en el instalador.**
   - Con `mblIpv6 true`, las sesiones de administración por IPv6 se añaden a `mbl6-allow` como `MBL: admin`.
   - Con `false`, se borra cualquier objeto `mbl6-*` o regla IPv6 `MBL:` de una instalación anterior.
9. **Comprobaciones de la allowlist de CDN.**
   - Una descarga de CDN se rechaza (y se usa la copia guardada) si no se puede leer, si trae menos de 5 prefijos o si incluye algo más amplio que /8.
   - El build falla si la allowlist elimina más del 10 % de las entradas de la lista.
10. **Versiones.**
    - `VERSION` se crea en la fase 2, porque la cabecera ya la necesita.
    - La comparación es numérica por componentes (`3.0.0` < `3.1.0`).
    - El objetivo de 2 min en el hAP ax3 se comprueba cuando el usuario pueda probarlo; hasta entonces solo cuenta la medida en el CHR.

## 8. Lo que queda a criterio del builder

- Cómo arrancar y automatizar el CHR en el CI (consola serie, `expect`, configuración inicial) y cómo servir la lista por HTTPS de prueba.
- El tamaño de trozo y el bucle de lectura en RouterOS, siempre que se cumplan las validaciones y los objetivos de tiempo.
- La composición exacta de *lite* dentro del objetivo de ≤ 10.000 entradas.
- Los mínimos de seguridad de IPv6 y el prefijo máximo IPv6, calibrados con datos reales y documentados.
- La forma exacta de la plantilla de issues y de `docs/security.md`.
