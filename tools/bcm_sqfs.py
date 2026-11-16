"""SquashFS 4.0 variante Broadcom (magic 'shsq', LZMA "alone" con tamaño conocido, bloques de 64 KiB).

  py -I bcm_sqfs.py extract <rootfs.sqfs> <dir>      -> <dir>/rootfs/... + <dir>/manifest.tsv
  py -I bcm_sqfs.py build   <dir> <salida.sqfs>      -> imagen nueva desde rootfs/ + manifest.tsv
  py -I bcm_sqfs.py compare <a.sqfs> <b.sqfs>        -> compara contenido y metadatos entrada por entrada

El manifest guarda lo que Windows no puede representar (modo, uid/gid, mtime, symlinks, dispositivos).
Archivos nuevos en rootfs/ que no estén en el manifest se agregan con modo 0644 (carpetas 0755).
"""
import hashlib, lzma, os, stat, struct, sys, time

BS = 0x10000                     # tamaño de bloque (block_log 16)
META = 0x2000                    # bloque de metadatos sin comprimir
NOFRAG = 0xFFFFFFFF
LZ = {'id': lzma.FILTER_LZMA1, 'dict_size': BS, 'lc': 3, 'lp': 0, 'pb': 2}
T_DIR, T_FILE, T_LNK, T_BLK, T_CHR, T_FIFO, T_SOCK = range(1, 8)
FMT = {stat.S_IFDIR: T_DIR, stat.S_IFREG: T_FILE, stat.S_IFLNK: T_LNK, stat.S_IFBLK: T_BLK,
       stat.S_IFCHR: T_CHR, stat.S_IFIFO: T_FIFO, stat.S_IFSOCK: T_SOCK}
NAMES = {T_DIR: 'dir', T_FILE: 'file', T_LNK: 'link', T_BLK: 'blk', T_CHR: 'chr', T_FIFO: 'fifo', T_SOCK: 'sock'}


# ---------- compresión ----------
def bcm_decompress(src):
    n = struct.unpack('<Q', src[5:13])[0]
    return lzma.LZMADecompressor(lzma.FORMAT_RAW, filters=[LZ]).decompress(src[13:], n)


def bcm_compress(raw):
    """Cabecera lzma-alone (props 0x5D, dict 64K, tamaño real) + stream LZMA1.
    liblzma agrega marca de fin; el decodificador de Broadcom corta por tamaño y no la lee."""
    body = lzma.compress(raw, lzma.FORMAT_RAW, filters=[dict(LZ, preset=9 | lzma.PRESET_EXTREME)])
    return b'\x5d' + struct.pack('<IQ', BS, len(raw)) + body


# ---------- lectura (PySquashfsImage, implementación independiente de la escritura) ----------
def open_image(path):
    import PySquashfsImage as P
    import PySquashfsImage.compressor as C

    class BcmLzma(C.Compressor):
        name = 'lzma-bcm'

        def uncompress(self, src, size, outsize):
            return bcm_decompress(src)
    P.compressors[1] = BcmLzma
    d = open(path, 'rb').read()
    assert d[:4] in (b'shsq', b'hsqs'), 'no es squashfs'
    return P.SquashFsImage.from_bytes(b'hsqs' + d[4:])


def entries(img):
    """path -> (tipo, permisos, uid, gid, mtime, extra) ; extra = sha1 | destino | 'major,minor'"""
    out = {}
    for f in img:
        i = f.inode
        t = FMT[stat.S_IFMT(i.mode)]
        if t == T_FILE:
            extra = f.read_bytes()
        elif t == T_LNK:
            extra = i.symlink
        elif t in (T_BLK, T_CHR):
            r = i._rdev
            extra = f'{(r & 0xFFF00) >> 8},{(r & 0xFF) | ((r >> 12) & 0xFFF00)}'
        else:
            extra = ''
        out[f.path or '/'] = (t, stat.S_IMODE(i.mode), f.uid, f.gid, i.time, extra)
    return out


def cmd_extract(sqfs, dest):
    root = os.path.join(dest, 'rootfs')
    os.makedirs(root, exist_ok=True)
    rows, seen = [], set()
    for p, (t, mode, uid, gid, mt, extra) in sorted(entries(open_image(sqfs)).items()):
        rel, alt = p.lstrip('/'), ''
        if t == T_FILE and rel.lower() in seen:  # Windows no distingue mayúsculas: xt_DSCP.ko vs xt_dscp.ko
            rel = alt = rel + '~case'
        seen.add(rel.lower())
        disk = os.path.join(root, rel)
        if t == T_DIR:
            os.makedirs(disk, exist_ok=True)
        elif t == T_FILE:
            os.makedirs(os.path.dirname(disk), exist_ok=True)
            open(disk, 'wb').write(extra)
        rows.append(f"{p}\t{NAMES[t]}\t{mode:04o}\t{uid}\t{gid}\t{mt}\t{alt if t == T_FILE else extra}")
    open(os.path.join(dest, 'manifest.tsv'), 'w', encoding='utf-8', newline='\n').write('\n'.join(rows) + '\n')
    print(f'{len(rows)} entradas extraídas en {dest}')


# ---------- escritura ----------
class Meta:
    """Tabla de metadatos: bloques de 8 KiB comprimidos con cabecera u16 (bit 15 = sin comprimir)."""

    def __init__(self):
        self.out, self.buf = bytearray(), bytearray()

    def pos(self):  # (inicio comprimido del bloque actual, offset dentro del bloque)
        return len(self.out), len(self.buf)

    def add(self, b):
        self.buf += b
        while len(self.buf) >= META:
            self._flush(META)

    def _flush(self, n):
        raw, self.buf = bytes(self.buf[:n]), self.buf[n:]
        c = bcm_compress(raw)
        self.out += struct.pack('<H', len(c)) + c if len(c) < len(raw) else struct.pack('<H', len(raw) | 0x8000) + raw

    def done(self):
        if self.buf:
            self._flush(len(self.buf))
        return bytes(self.out)


def load_tree(src):
    root = os.path.join(src, 'rootfs')
    nodes = {}
    for line in open(os.path.join(src, 'manifest.tsv'), encoding='utf-8'):
        p, t, mode, uid, gid, mt, extra = line.rstrip('\n').split('\t')
        nodes[p] = {'t': {v: k for k, v in NAMES.items()}[t], 'mode': int(mode, 8), 'uid': int(uid),
                    'gid': int(gid), 'mt': int(mt), 'extra': extra}
    now = int(time.time())
    known = {('/' + n['extra']).lower() for n in nodes.values() if n['t'] == T_FILE and n['extra']}
    known |= {p.lower() for p in nodes}
    for dp, dns, fns in os.walk(root):
        for n in dns + fns:
            full = os.path.join(dp, n)
            p = '/' + os.path.relpath(full, root).replace(os.sep, '/')
            if p.lower() not in known:
                isdir = os.path.isdir(full)
                print('  nuevo:', p)
                nodes[p] = {'t': T_DIR if isdir else T_FILE, 'mode': 0o755 if isdir else 0o644,
                            'uid': 0, 'gid': 0, 'mt': now, 'extra': ''}
    for p, n in nodes.items():
        if n['t'] == T_FILE:
            disk = os.path.join(root, n['extra'] or p.lstrip('/'))
            assert os.path.isfile(disk), f'falta en disco (borralo también del manifest): {p}'
            n['data'] = open(disk, 'rb').read()
        n['kids'] = []
    for p in sorted(nodes):
        if p != '/':
            nodes[p.rsplit('/', 1)[0] or '/']['kids'].append(p)
    return nodes


def cmd_build(src, out_path):
    nodes = load_tree(src)
    ids = sorted({n['uid'] for n in nodes.values()} | {n['gid'] for n in nodes.values()})
    data = bytearray(b'\0' * 96)
    frags, fbuf, dedup = [], bytearray(), {}

    def flush_frag():
        nonlocal fbuf
        if fbuf:
            c = bcm_compress(bytes(fbuf))
            store = c if len(c) < len(fbuf) else bytes(fbuf)
            frags.append((len(data), len(store) | (0 if store is c else 1 << 24)))
            data.extend(store)
            fbuf = bytearray()

    # 1) datos: bloques enteros + colas en fragmentos (con deduplicación de archivos idénticos)
    for p in sorted(nodes):
        n = nodes[p]
        if n['t'] != T_FILE:
            continue
        b = n['data']
        h = hashlib.sha1(b).digest()
        if h in dedup:
            n['loc'] = dedup[h]
            continue
        start, sizes = len(data), []
        full = len(b) // BS * BS
        for o in range(0, full, BS):
            raw = b[o:o + BS]
            c = bcm_compress(raw)
            store = c if len(c) < len(raw) else raw
            sizes.append(len(store) | (0 if store is c else 1 << 24))
            data.extend(store)
        tail = b[full:]
        frag, off = NOFRAG, 0
        if tail:
            if len(fbuf) + len(tail) > BS:
                flush_frag()
            frag, off = len(frags), len(fbuf)
            fbuf += tail
        n['loc'] = dedup[h] = (start, sizes, frag, off)
    flush_frag()

    # 2) numeración post-orden (hijos antes que el padre, raíz = último)
    order = []

    def number(p):
        for k in nodes[p]['kids']:
            if nodes[k]['t'] == T_DIR:
                number(k)
            else:
                order.append(k)
        order.append(p)
    number('/')
    for i, p in enumerate(order, 1):
        nodes[p]['ino'] = i
    count = len(order)

    # 3) inodos + directorios (cada directorio se escribe después de sus hijos)
    itab, dtab = Meta(), Meta()

    def hdr(n, t):
        return struct.pack('<HHHHII', t, n['mode'], ids.index(n['uid']), ids.index(n['gid']), n['mt'], n['ino'])

    def write_inode(p, parent_ino):
        n = nodes[p]
        t = n['t']
        if t == T_DIR:
            for k in n['kids']:
                if nodes[k]['t'] == T_DIR:
                    write_inode(k, n['ino'])
                else:
                    write_inode(k, None)
            dstart, doff = dtab.pos()
            listing = bytearray()
            kids = sorted(n['kids'], key=lambda k: k.rsplit('/', 1)[1].encode())
            i = 0
            while i < len(kids):  # grupos: mismo bloque de inodos, <=256 entradas, delta en s16
                blk, base = nodes[kids[i]]['ref'][0], nodes[kids[i]]['ino']
                grp = []
                while (i < len(kids) and len(grp) < 256 and nodes[kids[i]]['ref'][0] == blk
                       and -32768 <= nodes[kids[i]]['ino'] - base <= 32767):
                    grp.append(kids[i])
                    i += 1
                listing += struct.pack('<III', len(grp) - 1, blk, base)
                for k in grp:
                    name = k.rsplit('/', 1)[1].encode()
                    listing += struct.pack('<HhHH', nodes[k]['ref'][1], nodes[k]['ino'] - base,
                                           nodes[k]['t'], len(name) - 1) + name
            dtab.add(bytes(listing))
            assert len(listing) + 3 <= 0xFFFF, f'directorio demasiado grande: {p}'
            nlink = 2 + sum(nodes[k]['t'] == T_DIR for k in n['kids'])
            body = struct.pack('<IIHHI', dstart, nlink, len(listing) + 3, doff,
                               parent_ino if parent_ino else count + 1)
        elif t == T_FILE:
            start, sizes, frag, off = n['loc']
            body = struct.pack('<IIII', start, frag, off, len(n['data'])) + b''.join(struct.pack('<I', s) for s in sizes)
        elif t == T_LNK:
            target = n['extra'].encode()
            body = struct.pack('<II', 1, len(target)) + target
        elif t in (T_BLK, T_CHR):
            ma, mi = map(int, n['extra'].split(','))
            body = struct.pack('<II', 1, (mi & 0xFF) | (ma << 8) | ((mi & ~0xFF) << 12))
        else:
            body = struct.pack('<I', 1)
        n['ref'] = itab.pos()
        itab.add(hdr(n, t) + body)

    write_inode('/', None)
    root_ref = (nodes['/']['ref'][0] << 16) | nodes['/']['ref'][1]

    # 4) tablas y superbloque
    def table(entries_bytes):
        m = Meta()
        starts = []
        for o in range(0, len(entries_bytes), META):
            starts.append(m.pos()[0])
            m.add(entries_bytes[o:o + META])
        return m.done(), starts

    inode_start = len(data); data += itab.done()
    dir_start = len(data); data += dtab.done()
    fb, fstarts = table(b''.join(struct.pack('<QII', s, z, 0) for s, z in frags))
    fpos = len(data); data += fb
    frag_start = len(data); data += b''.join(struct.pack('<Q', fpos + s) for s in fstarts)
    ib, istarts = table(b''.join(struct.pack('<I', x) for x in ids))
    ipos = len(data); data += ib
    id_start = len(data); data += b''.join(struct.pack('<Q', ipos + s) for s in istarts)
    used = len(data)
    data[:96] = struct.pack('<4sIIIIHHHHHHQQQQQQQQ', b'shsq', count, int(time.time()), BS, len(frags), 1, 16,
                            0x40 if dedup else 0, len(ids), 4, 0, root_ref, used, id_start,
                            0xFFFFFFFFFFFFFFFF, inode_start, dir_start, frag_start, 0xFFFFFFFFFFFFFFFF)
    data += b'\0' * (-used % 4096)  # mksquashfs alinea a 4 KiB
    open(out_path, 'wb').write(data)
    print(f'{count} entradas, {len(frags)} fragmentos, {used} bytes usados -> {out_path} ({len(data)} con relleno)')


def cmd_compare(a, b):
    ea, eb = entries(open_image(a)), entries(open_image(b))
    bad = [p for p in sorted(set(ea) | set(eb)) if ea.get(p) != eb.get(p)]
    for p in bad[:30]:
        print('DIFIERE', p, (ea.get(p) or ('falta',))[:5], (eb.get(p) or ('falta',))[:5])
    print(f'{len(ea)} vs {len(eb)} entradas, {len(bad)} diferencias')
    return not bad


if __name__ == '__main__':
    cmd, *args = sys.argv[1:]
    r = {'extract': cmd_extract, 'build': cmd_build, 'compare': cmd_compare}[cmd](*args)
    sys.exit(0 if r is not False else 1)
