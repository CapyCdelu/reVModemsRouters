# reVModemsRouters

Reciclar módems ADSL viejos de proveedores (Telecom, etc.) como **routers básicos**: se le saca la capa del proveedor (TR-069, DSL, interfaz web con marca), se pasa un puerto LAN a WAN y se pone una interfaz web sencilla para configurar router, wifi e IPs.

La idea es **modificar el firmware de fábrica**, no reemplazarlo por OpenWrt. Así se conservan los drivers propietarios (switch, wifi), que en estos equipos suelen andar mejor que los libres, y se evita portar un dispositivo que OpenWrt no soporta.

> Este repositorio contiene **solo herramientas y documentación**. No incluye firmwares, volcados ni configuraciones: tienen copyright del fabricante y además guardan claves y datos del equipo. Cada uno trabaja sobre el volcado de su propio módem.

## Estado

| Modelo | Chip | Estado |
|---|---|---|
| [ADB P.DG A4001N (Telecom AR, board 96328dg2x2)](docs/modelos/adb-a4001n-telecom-ar.md) | BCM6328 | Etapa 1 ✅ en PC (rootfs reconstruido idéntico) · falta probar en el equipo |

## Herramientas (`tools/`)

Python 3.11+, en Windows o Linux. Para leer squashfs: `pip install -r requirements.txt`.

| Herramienta | Qué hace |
|---|---|
| `bcm_image.py` | Lee el bcmTag (cabecera de imagen Broadcom) de un volcado SPI, verifica y recalcula los 4 CRC, separa rootfs y kernel, y arma imágenes nuevas (volcado completo para grabador + imagen para el CFE) |
| `bcm_sqfs.py` | Extrae y **reconstruye** el SquashFS 4.0 de Broadcom (magic `shsq`, LZMA por bloque). Guarda permisos, symlinks y dispositivos en un `manifest.tsv`, porque Windows no los representa |
| `bcm_cfg.py` | Descomprime la config guardada (PSI, LZW de Broadcom) a XML |

### Flujo

```sh
py -I tools/bcm_image.py info  volcado.bin                 # identificar y validar CRC
py -I tools/bcm_image.py split volcado.bin work            # work/rootfs.sqfs + work/kernel.bin
py -I tools/bcm_sqfs.py extract work/rootfs.sqfs work/fs   # work/fs/rootfs/ + work/fs/manifest.tsv
#   ... modificar work/fs/rootfs/ (y manifest.tsv para modos/borrados) ...
py -I tools/bcm_sqfs.py build   work/fs work/nuevo.sqfs
py -I tools/bcm_sqfs.py compare work/rootfs.sqfs work/nuevo.sqfs   # qué cambió
py -I tools/bcm_image.py build volcado.bin work/nuevo.sqfs work/salida
#   -> work/salida_spi.bin (grabador SPI)  /  work/salida_cfe.bin (web de recuperación del CFE)
```

Primera prueba obligatoria en cualquier modelo: **extraer y reconstruir sin cambios** (`compare` tiene que dar 0 diferencias) y bootear esa imagen. Recién después tocar algo.

## Documentación

- [Método general](docs/metodo.md): cómo encarar otro modelo desde cero.
- [Modelos](docs/modelos/): hallazgos, offsets y estado de cada equipo.

## Advertencia

Grabar firmware modificado puede dejar el equipo sin arrancar. Antes de empezar, hacé un **volcado completo de la flash con un grabador SPI** (CH341A o similar) y guardalo: es lo único que garantiza volver atrás.
