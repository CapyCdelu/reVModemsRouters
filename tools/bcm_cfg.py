"""Config persistente (PSI) de Broadcom CMS: '<compressed alg=lzw len=N>' + '<crc=0x...>' + LZW.

  py -I bcm_cfg.py dump <volcado.bin> <salida.xml> [offset_hex]

Si no se da offset, busca la cabecera '<compressed alg=lzw' en el volcado.
LZW de Broadcom: códigos MSB-first de 9 a 12 bits, 256 = clear, 257 = fin; datos desde cabecera + 0x3C.
"""
import re, sys


def lzw_decode(data):
    dic = {i: bytes([i]) for i in range(256)}
    nxt, w, out, prev = 258, 9, bytearray(), None
    acc = nb = i = 0
    while True:
        while nb < w and i < len(data):
            acc, nb, i = (acc << 8) | data[i], nb + 8, i + 1
        if nb < w:
            break
        nb -= w
        c, acc = (acc >> nb) & ((1 << w) - 1), acc & ((1 << nb) - 1)
        if c == 256:
            dic, nxt, w, prev = {i: bytes([i]) for i in range(256)}, 258, 9, None
            continue
        if c == 257:
            break
        if c in dic:
            e = dic[c]
        elif c == nxt and prev is not None:
            e = prev + prev[:1]
        else:
            raise ValueError(f'código LZW inválido {c} en byte {i}')
        out += e
        if prev is not None and nxt < 4096:
            dic[nxt], nxt = prev + e[:1], nxt + 1
        if nxt + 1 >= (1 << w) and w < 12:
            w += 1
        prev = e
    return bytes(out)


def cmd_dump(path, out, off=None):
    d = open(path, 'rb').read()
    o = int(off, 16) if off else d.find(b'<compressed alg=lzw')
    assert o >= 0, 'no se encontró config LZW'
    n = int(re.search(rb'len=(\d+)', d[o:o + 40]).group(1))
    xml = lzw_decode(d[o + 0x3C:o + 0x3C + n])
    assert xml.startswith(b'<?xml'), 'la descompresión no dio XML'
    open(out, 'wb').write(xml)
    print(f'config en 0x{o:x}: {n} bytes LZW -> {len(xml)} bytes XML -> {out}')


if __name__ == '__main__':
    cmd, *args = sys.argv[1:]
    {'dump': cmd_dump}[cmd](*args)
