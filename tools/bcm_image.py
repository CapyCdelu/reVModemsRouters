"""Imagen Broadcom bcmTag v6 ("ver. 2.0") en un volcado SPI completo: CFE | tag + rootfs + kernel | config.

  py -I bcm_image.py info  <volcado.bin>
  py -I bcm_image.py split <volcado.bin> <dir>            -> rootfs.sqfs, kernel.bin
  py -I bcm_image.py build <volcado.bin> <rootfs.sqfs> <salida_prefijo>
        -> <prefijo>_spi.bin  (volcado completo para grabador; CFE y config intactos)
           <prefijo>_cfe.bin  (tag + rootfs + kernel, para la web de recuperación del CFE)

Offsets del tag tomados del ADB A4001N (Telecom AR). Verificar con `info` antes de usar en otro modelo.
"""
import struct, sys, zlib

TAG = 0x10000           # el tag arranca después del bloque de 64 KiB del CFE
FLASH_BASE = 0xBFC00000  # dirección donde el CFE mapea la flash
# campo: (offset, largo) — cadenas ASCII terminadas en \0
F = {'version': (0x00, 4), 'sig1': (0x04, 20), 'sig2': (0x18, 14), 'chip': (0x26, 6), 'board': (0x2C, 16),
     'big_endian': (0x3C, 2), 'total_len': (0x3E, 10), 'cfe_addr': (0x48, 12), 'cfe_len': (0x54, 10),
     'rootfs_addr': (0x5E, 12), 'rootfs_len': (0x6A, 10), 'kernel_addr': (0x74, 12), 'kernel_len': (0x80, 10)}
CRC_IMAGE, CRC_ROOTFS, CRC_KERNEL, CRC_TAG = 0xD8, 0xDC, 0xE0, 0xEC


def crc(b):
    return zlib.crc32(b) ^ 0xFFFFFFFF  # CRC32 de Broadcom: init 0xFFFFFFFF, sin xor final


def get(t, k):
    o, n = F[k]
    return t[o:o + n].split(b'\0')[0].decode()


def put(t, k, v):
    o, n = F[k]
    v = str(v).encode()
    assert len(v) < n, f'{k} no entra en el tag'
    t[o:o + n] = v + b'\0' * (n - len(v))


def parse(d):
    t = bytearray(d[TAG:TAG + 0x100])
    assert get(t, 'sig1').startswith('Broadcom'), 'no hay bcmTag en 0x10000'
    rofs = int(get(t, 'rootfs_addr')) - FLASH_BASE
    rlen, klen = int(get(t, 'rootfs_len')), int(get(t, 'kernel_len'))
    kofs = int(get(t, 'kernel_addr')) - FLASH_BASE
    return t, rofs, rlen, kofs, klen


def check(d):
    t, rofs, rlen, kofs, klen = parse(d)
    r, k = d[rofs:rofs + rlen], d[kofs:kofs + klen]
    want = {'imagen': (CRC_IMAGE, crc(r + k)), 'rootfs': (CRC_ROOTFS, crc(r)),
            'kernel': (CRC_KERNEL, crc(k)), 'tag': (CRC_TAG, crc(bytes(t[:CRC_TAG])))}
    return {n: struct.unpack('>I', t[o:o + 4])[0] == v for n, (o, v) in want.items()}


def cmd_info(path):
    d = open(path, 'rb').read()
    t, rofs, rlen, kofs, klen = parse(d)
    for k in F:
        print(f'{k:12} {get(t, k)}')
    print(f'rootfs flash 0x{rofs:x}+{rlen}  kernel flash 0x{kofs:x}+{klen}  fin 0x{kofs + klen:x}')
    print('CRC ok:', check(d))


def cmd_split(path, dest):
    import os
    d = open(path, 'rb').read()
    t, rofs, rlen, kofs, klen = parse(d)
    os.makedirs(dest, exist_ok=True)
    open(os.path.join(dest, 'rootfs.sqfs'), 'wb').write(d[rofs:rofs + rlen])
    open(os.path.join(dest, 'kernel.bin'), 'wb').write(d[kofs:kofs + klen])
    print('ok', dest)


def cmd_build(path, rootfs_path, out):
    d = bytearray(open(path, 'rb').read())
    t, rofs, rlen, kofs, klen = parse(d)
    assert all(check(d).values()), 'el volcado original no pasa los CRC'
    r, k = open(rootfs_path, 'rb').read(), bytes(d[kofs:kofs + klen])
    assert rofs == TAG + 0x100 and kofs == rofs + rlen, 'layout inesperado (rootfs pegado al tag y kernel detrás)'
    # el área de imagen termina donde empieza lo que no es imagen (config/nvram): el primer byte no-FF tras el kernel
    end = next(i for i in range(kofs + klen, len(d)) if d[i] != 0xFF) & ~0xFFFF
    new_end = rofs + len(r) + len(k)
    assert new_end <= end, f'la imagen nueva ({new_end:#x}) pisa la zona de config ({end:#x})'
    put(t, 'rootfs_len', len(r))
    put(t, 'kernel_addr', FLASH_BASE + rofs + len(r))
    put(t, 'total_len', len(r) + len(k))
    t[CRC_IMAGE:CRC_IMAGE + 12] = struct.pack('>III', crc(r + k), crc(r), crc(k))
    t[CRC_TAG:CRC_TAG + 4] = struct.pack('>I', crc(bytes(t[:CRC_TAG])))
    img = bytes(t) + r + k
    d[TAG:end] = img + b'\xff' * (end - TAG - len(img))
    assert all(check(d).values())
    open(out + '_spi.bin', 'wb').write(d)
    open(out + '_cfe.bin', 'wb').write(img)
    print(f'ok: imagen {len(img)} bytes (libre hasta config: {end - TAG - len(img)}) -> {out}_spi.bin / {out}_cfe.bin')


if __name__ == '__main__':
    cmd, *args = sys.argv[1:]
    {'info': cmd_info, 'split': cmd_split, 'build': cmd_build}[cmd](*args)
