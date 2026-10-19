# Validación en CHR v7 (Proxmox)

Guía para montar un RouterOS CHR de pruebas y registrar el resultado de la Tarea 9. Los scripts a validar son `routeros/install.rsc` y `routeros/uninstall.rsc`.

## 1. Crear la VM CHR en Proxmox

1. Descarga la imagen **CHR raw** (`chr-<ver>.img.zip`) de <https://mikrotik.com/download> (sección *Cloud Hosted Router*). Elige la última **7.x stable, >= 7.21**.
2. En el host Proxmox:

```bash
VMID=9100                      # cualquier ID libre
BRIDGE_LAN=vmbrTEST            # bridge aislado de pruebas (sin salida)
unzip chr-*.img.zip            # produce chr-<ver>.img

qm create $VMID --name mbl-chr --memory 256 --cores 1 \
  --net0 virtio,bridge=vmbr0 --net1 virtio,bridge=$BRIDGE_LAN \
  --ostype l26 --serial0 socket
qm importdisk $VMID chr-*.img local-lvm
qm set $VMID --scsi0 local-lvm:vm-$VMID-disk-0 --scsihw virtio-scsi-pci --boot order=scsi0
qm start $VMID
```

- `net0` = **ether1 = WAN**: bridge con salida a Internet (necesario para `/tool fetch` a GitHub).
- `net1` = **ether2 = LAN**: bridge aislado de pruebas. Si quieres un host de prueba, conéctalo a este bridge.
- Si el almacenamiento no es `local-lvm`, ajusta el nombre. Comprueba el nombre exacto del disco con `qm config $VMID` (aparece como `unused0`).
- Para la rendimiento (caso 13) puedes subir a `--memory 512` y repetir.
- Consola: `qm terminal $VMID` (serie) o la consola web. Usuario `admin`, contraseña vacía.

## 2. Configuración mínima en el CHR

Por consola (`qm terminal $VMID`):

```routeros
/user set admin password="CAMBIAME"
/ip dhcp-client add interface=ether1 disabled=no
/ip address add address=192.168.88.1/24 interface=ether2
/interface list add name=WAN
/interface list add name=LAN
/interface list member add list=WAN interface=ether1
/interface list member add list=LAN interface=ether2
/ip service set ssh disabled=no
/system identity set name=mbl-chr
/ip dhcp-client print
/system resource print
```

Anota la IP que obtenga `ether1` (`/ip dhcp-client print`).

### Clave SSH

Copia la clave pública de este equipo (`/home/antonio/.ssh/antonio.pub`) al CHR. Con SSH por contraseña ya activo:

```bash
scp /home/antonio/.ssh/antonio.pub admin@<IP_CHR>:antonio.pub
```

Alternativa sin red (pegar por consola): `/file add name=antonio.pub contents="<contenido de antonio.pub>"`.

Después, en el CHR:

```routeros
/user ssh-keys import public-key-file=antonio.pub user=admin
```

Comprueba desde este equipo: `ssh -i /home/antonio/.ssh/antonio admin@<IP_CHR> /system resource print` (si tu clave privada es la de por defecto, no hace falta `-i`).

### Avisar a Claude

Dile a Claude la **IP del CHR** (la de ether1, alcanzable desde este equipo) y confirma que el SSH con clave funciona. Con eso Claude lanza los casos de prueba por SSH.

## 3. Casos de prueba

Rellena *Estado* con OK / FALLO.

| # | Caso | Cómo | Resultado esperado | Estado |
|---|------|------|--------------------|--------|
| 1 | Instalación limpia | Fetch + `/import install.rsc` | 5 reglas raw `MBL:` (+ allow-router-out), 2 schedulers (`mbl-daily`, `mbl-boot`), script `mbl-update`; `mbl-a` con >= 1000 entradas | |
| 2 | Bloqueo entrante | Añadir a mano una IP de prueba a la lista activa; generar tráfico desde WAN (`/tool fetch` desde un host) o mirar contadores | `MBL: in` cuenta paquetes | |
| 3 | Bloqueo saliente | `ping` desde un host LAN a una IP de la lista; `/ping` desde el router | Log `MBL-OUT`; el `/ping` del router se bloquea por `MBL: router-out` | |
| 4 | Actualización | `/system script run mbl-update` | Las reglas pasan a `mbl-b`; `mbl-a` queda vacía | |
| 5 | Fichero truncado | Servir un `.rsc` sin el pie | Se mantiene la lista anterior; error en el log | |
| 6 | URL caída | Apuntar a una URL inexistente y ejecutar | Se mantiene la lista anterior | |
| 7 | Ejecución concurrente | Dos `/system script run mbl-update` seguidos | El segundo sale por el lock | |
| 8 | Reinicio con red | `/system reboot` con WAN | La lista se carga desde `mbl-last.rsc` en segundos y luego se actualiza | |
| 9 | Arranque sin red | `ether1` desactivada + reinicio | La lista se carga desde `mbl-last.rsc` | |
| 10 | Reinstalación | Volver a importar `install.rsc` | Nada duplicado; se conserva `MBL: admin` (y la lista activa) | |
| 11 | IP de gestión listada | Poner la IP del admin en la lista activa | Se mantiene el acceso SSH | |
| 12 | Desinstalación | `/import uninstall.rsc` | No queda nada `mbl`/`MBL:`; la config del usuario intacta | |
| 13 | Rendimiento | `/system resource print` antes y después, con la lista real; medir el tiempo de importación | Tiempo y RAM anotados (aprox. 32k entradas) | |

Notas de rendimiento: tiempo de import = ______ ; RAM libre antes = ______ ; después = ______.

## 4. Puntos a verificar del script (Tarea 8)

| # | Punto | Estado |
|---|-------|--------|
| 1 | Bloque multilínea `{ ... }` en `/import`: locales, funciones y continuaciones `\` | |
| 2 | `source={...}` guarda el cuerpo literal (`$var`), sin quejas de variables sin declarar; `get source` correcto y el reemplazo de URL con `:find`/`:pick` | |
| 3 | Nombre exacto de `builtin-trust-store` en la versión mínima; `get` (string/array); `$ts != "all"`; sintaxis `set builtin-trust-store=fetch,...`; `check-certificate=yes` a raw.githubusercontent.com. Fijar `mblMinVersion` | |
| 4 | Idioma `:parse` + `$f`: `:return` devuelve valor; errores en ejecución capturados por `:do on-error` | |
| 5 | Funciones con `$1` posicional (`mblVerNum`, `mblPad`); `:while` con `[:pick $rest $e] ~ "[0-9]"` | |
| 6 | `/user active get $s address` con `:tostr`: vacío en consola; IPv6/MAC fallan dentro de `on-error` | |
| 7 | `/tool fetch ... check-certificate=yes` sin `as-value` bloquea hasta terminar y el fallo lo captura `on-error`; ¿hace falta/basta el delay de 2 s? | |
| 8 | `/file get [find where name=$fname] size` devuelve bytes; `name` sin prefijo `flash/` | |
| 9 | `/import verbose=no` desde scheduler: globals `mblTarget`/`mblImportOk` compartidos; fichero truncado deja `mblImportOk=false`; tiempo con ~32k entradas | |
| 10 | Globals compartidos entre el scheduler (`:global mblBoot true`) y `/system script run mbl-update` | |
| 11 | `/file set name=` y `/file copy` existen en la versión mínima; cuál se usa | |
| 12 | `remove [find where list=...]` sobre entradas con timeout; los timeouts se pierden al reiniciar (modo boot necesario) | |
| 13 | Reglas raw con listas aún inexistentes (`mbl-allow`, `mbl-a`); `log=yes log-prefix=` aceptado en raw | |
| 14 | `place-before=<id interno>` en `/ip firewall raw`; las reglas quedan arriba en orden | |
| 15 | Scheduler `start-time=HH:MM:SS` sin `start-date` corre a diario; la política `ftp,read,write,policy,test` basta (script y scheduler) | |
| 16 | Uninstall: `where list="mbl-allow" and comment="MBL: admin"`, regex `^(flash/)?mbl-.*\.rsc$`, `/system script environment remove` | |
| 17 | `flash/`: detección con `/file find where name="flash"`, `dst-path`, `/import file-name=flash/...`, persistencia tras reinicio (CHR no lo tiene: solo se prueba el prefijo vacío) | |
| 18 | `mblMove`: `:parse` de cadena construida dentro de función, retorno en `:if ([$mblMove a b])` y `![...]`, `file remove [find where name=$1]`; probar rutas de recuperación forzando fallo de rename | |
| 19 | Reinstalación con ambas listas pobladas: reglas sobre la lista activa previa y sin ventana con la activa vacía | |
| 20 | `mblLastOk`/`mblRunning` visibles al instalador tras `/system script run` (mensaje instalado / primera carga fallida correcto) | |
