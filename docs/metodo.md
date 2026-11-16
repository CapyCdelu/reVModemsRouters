# Método general

Pasos para encarar un módem nuevo. Están pensados para equipos Broadcom con CFE (bcm63xx), pero la lógica sirve para otros.

## 0. Volcado y respaldo

1. Abrir el equipo, ubicar la flash SPI (W25Qxx, MX25Lxx…) y leerla **dos veces** con el grabador (CH341A + clip SOIC8). Comparar las dos lecturas: tienen que ser idénticas.
2. Guardar el volcado fuera del repo. Es la única vuelta atrás garantizada.

## 1. Identificar

- **Bootloader:** los primeros bytes del volcado. En Broadcom, el CFE ocupa el primer bloque de 64 KiB. Buscar el string `cfe-<modelo>` y los parámetros de arranque (`e=192.168.1.1:ffffff00 ...`), que dan la IP del modo de recuperación.
- **Cabecera de imagen:** en `0x10000` suele estar el bcmTag (`Broadcom Corporatio`, `ver. 2.0`), con chip, board id y direcciones y largos del rootfs y el kernel. `bcm_image.py info` lo decodifica y valida los CRC.
- **Mapa por entropía:** dividir la flash en bloques de 64 KiB y medir la entropía. ~8.0 = comprimido, `FF` = vacío y valores bajos = config o texto. Así se ubican el rootfs, el kernel, la zona libre y la config.
- **No asumir cifrado** por ver entropía 8.0: primero buscar firmas (`hsqs`, `sqsh`, `shsq`, `qshs`) justo después de la cabecera. En el A4001N el rootfs parecía cifrado y en realidad era squashfs con firma propia (`shsq`) en `0x10100`.

## 2. Leer la config

La config guardada (PSI) de Broadcom CMS está cerca del final de la flash: `<compressed alg=lzw len=N>` + `<crc=...>` + LZW. `bcm_cfg.py dump` la pasa a XML. Ahí se ve:
- qué interfaces existen (LAN `ethN`, WAN `atmN`/`pppN`, wifi `wl0`);
- si el firmware se compiló con **WAN por Ethernet** (aparece un `WANDevice` con `WANAccessType` = `Ethernet`);
- las credenciales de admin y de gestión remota del proveedor (TR-069).

## 3. Abrir el rootfs

`bcm_image.py split` + `bcm_sqfs.py extract`. Puntos a revisar:
- `/etc/default.cfg`: config que se carga **al resetear de fábrica**. Para que un cambio sobreviva al reset, tiene que ir acá (confirmar que `libcms_core.so` la referencia).
- `/webs/`: interfaz web (páginas + `menuBcm.js`). Las páginas llaman a acciones `*.cmd` del `httpd`.
- `/bin/tr69c`: cliente de gestión remota del proveedor.
- `/lib/modules/*/extra/wl.ko`, `bcm_enet.ko`: drivers propietarios. **No tocar.**
- El kernel (`kernel.bin`) es LZMA: cabecera de 12 bytes + props de 5 bytes + 8 bytes de tamaño. Sus strings indican qué descompresor de squashfs usa (`LZMA457 ported by BRCM` / `sqlzma`).

## 4. Validar la cadena de reconstrucción

**Antes de cambiar nada:** extraer → reconstruir → `compare` (0 diferencias) → `bcm_image.py build` → bootear en el equipo. Si eso arranca, cualquier falla posterior se debe a los cambios y no a las herramientas.

## 5. Modificar

Orden sugerido, de menor a mayor riesgo:
1. `default.cfg`: WAN por Ethernet en un puerto LAN, sacar las WAN DSL y desactivar TR-069.
2. Borrar del rootfs lo del proveedor (`tr69c`, páginas con marca).
3. Interfaz web propia sobre las mismas acciones `*.cmd` del `httpd` original.

## 6. Grabar

- **Grabador SPI:** `<prefijo>_spi.bin` (volcado completo con la imagen nueva y el CFE y la config originales).
- **Web de recuperación del CFE:** `<prefijo>_cfe.bin`. Se entra manteniendo reset mientras se enciende el equipo, en la IP de los parámetros de arranque.

## Trampas encontradas

- **Windows no distingue mayúsculas:** el rootfs puede tener `xt_DSCP.ko` y `xt_dscp.ko`. `bcm_sqfs.py extract` guarda el segundo como `~case` y lo registra en el manifest.
- **LZMA de Broadcom:** cada bloque lleva cabecera "alone" con el tamaño real y **sin** marca de fin. El `lzma` de Python siempre agrega la marca; el decodificador del kernel (SDK 4.57) corta por tamaño y no la lee. `liblzma` sí rechaza esa combinación, así que para verificar hay que decodificar en crudo.
- **Mover el kernel:** si el rootfs cambia de tamaño, el kernel se corre. `bcm_image.py build` actualiza `kernel_addr`, `rootfs_len` y `total_len` en el tag. El CFE lee la posición del kernel desde el tag.
