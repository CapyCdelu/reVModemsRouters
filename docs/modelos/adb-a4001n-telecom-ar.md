# ADB / Pirelli P.DG A4001N — Telecom Argentina

## Hardware (según el volcado)

| | |
|---|---|
| SoC | Broadcom BCM6328 (MIPS, big endian) |
| Flash | SPI W25Q64BV, **8 MiB** |
| Board id | `96328dg2x2` |
| Bootloader | CFE `cfe-A4001N-V0001`; recuperación en `192.168.1.1` |
| Kernel | Linux 2.6.30, squashfs 4.0 "with LZMA457 ported by BRCM" |
| Wifi | driver propietario `wl.ko` |
| LAN | `eth0`..`eth3` (switch interno, `bcm_enet.ko`) |
| RAM | sin confirmar (`cat /proc/meminfo` por SSH) |

**No es el A4001N de OpenWrt.** Ese tiene 16 MiB y board `963281T_TEF`. Este no tiene soporte y la familia quedó sin soporte después de 22.03.

## Mapa de la flash

| Offset | Contenido |
|---|---|
| `0x000000` | CFE (64 KiB). Parámetros de arranque en `~0x580` |
| `0x010000` | bcmTag v6 (256 bytes) |
| `0x010100` | rootfs: SquashFS 4.0 LE, magic `shsq`, LZMA alone por bloque, bloques de 64 KiB (~5,5 MB) |
| `0x552100` | kernel: cabecera CFE (load `0x80010000`, entry `0x80014230`) + LZMA (~1,1 MB) |
| `0x660000` | libre (`FF`) |
| `0x7F8000` | scratch pad (`gOGoBrCm`) |
| `0x7FA000` | config del usuario (PSI, LZW) |

CRC del tag en `0xD8` (imagen = rootfs+kernel), `0xDC` (rootfs), `0xE0` (kernel) y `0xEC` (tag, sobre los primeros `0xEC` bytes). Es el CRC32 de Broadcom: `zlib.crc32(x) ^ 0xFFFFFFFF`.

## Hallazgos del firmware

- **Soporte de WAN por Ethernet compilado:** la config y `default.cfg` traen un `WANDevice` con `WANAccessType=Ethernet` vacío, y `httpd`, `libcms_*` y `/webs/cfgeth.html` tienen la función "ETH WAN".
- `/etc/default.cfg` (XML, 35.740 bytes) se carga al resetear de fábrica (lo referencia `libcms_core.so`).
- Capa del proveedor: `tr69c` (TR-069 hacia el ACS de Telecom), WAN DSL `atm0`/`atm1` + PPPoE `ppp0`/`ppp1`, interfaz `/webs/` (221 archivos, 1,1 MB) y telnet.
- Las claves de admin, TR-069 y PPPoE están en la config. **No se publican acá**: se ven con `bcm_cfg.py dump` sobre el volcado propio.

## Bitácora

### 2026-11-15 — Etapa 1: cadena de reconstrucción
- Identificación, mapa de flash, tag y CRC validados.
- Config PSI descomprimida (LZW).
- `bcm_sqfs.py`: extracción y reconstrucción. Resultado: **656/656 entradas idénticas** (contenido, modo, uid/gid, mtime, symlinks, dispositivos). El rootfs nuevo queda unos 64 KB más chico que el original (LZMA preset 9e).
- `bcm_image.py build`: imagen completa con el kernel reubicado (`0x542100`) y los 4 CRC válidos. CFE y config byte a byte iguales al original.
- Riesgo pendiente: los bloques nuevos llevan marca de fin LZMA (el original no). El kernel usa `sqlzma`/`LzmaUncompress` (SDK 4.57), que corta por el tamaño de la cabecera, así que no debería afectar. Se confirma booteando.
- **Pendiente:** grabar la imagen de la etapa 1 (sin cambios funcionales) y confirmar que arranca.

### 2026-11-16 — Prueba en el equipo suspendida
- Se iba a grabar `etapa1_cfe.bin` por la web de recuperación del CFE, pero el equipo **no encendió (falla eléctrica)**, así que la imagen no llegó a grabarse.
- Al retomar: revisar la fuente o la alimentación, volver a leer la flash con el grabador y compararla con el volcado del 15-11 para confirmar que no cambió. Después seguir con el procedimiento de la sección siguiente.

## Procedimiento de grabado por CFE (web de recuperación)

1. PC con IP fija `192.168.1.100/255.255.255.0`, sin gateway, con un cable a un puerto LAN del módem y el wifi de la PC apagado.
2. `ping -t 192.168.1.1`.
3. Módem apagado → mantener reset → encender → seguir apretando 10-15 s → soltar.
4. `http://192.168.1.1` → página "CFE – Update Software" (sin marca de Telecom; si aparece el login de Telecom, repetir el paso 3).
5. Subir `<prefijo>_cfe.bin` → Update. No cortar la energía (1-3 min); se reinicia solo.
6. Verificar: ping, web, wifi y, por SSH, `cat /proc/meminfo`, `cat /proc/mtd`, `dmesg | grep -i -E "squashfs|lzma|error"`.
7. Si no arranca: volver al paso 3; si el CFE tampoco responde, grabar el volcado original con el grabador SPI.

## Próximas etapas

2. Relevar las acciones `*.cmd` del `httpd` (parámetros de cada página de WAN/LAN/wifi).
3. Interfaz nueva + `default.cfg` limpio (WAN Ethernet en el puerto 4, sin DSL ni TR-069) + borrar `tr69c`.
4. Grabar y probar en el equipo.
