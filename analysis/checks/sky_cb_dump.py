#!/usr/bin/env python3
"""Dump the named constant-buffer values of the sky draws in a packed capture (offline, read-only).

Why: the W1.1 census (2026-11-15) found which pixel shader draws the sky but not what drives its colour, and the
shader's RDEF names its inputs (`dump_shader_decls.py` parses those names, offsets and bind slots). This reads those
values out of one capture's constant-buffer blob per draw, so the W1.3 decision rests on the game's own numbers
instead of on the shader text alone.

Usage:
  sky_cb_dump.py <scene.manifest> [--cbs PATH] [--shaders DIR] [--ps HEX] [--json PATH] [--names a,b,c]
Read-only. Exits 1 with a message (no traceback) when the manifest is damaged, a shader or cbblob is missing, a
requested value lies outside the constant buffer the draw binds, or a declared slot is not bound; never dumps zeros.
"""
import json
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dump_shader_decls as decls  # noqa: E402  RDEF name/offset parser already gate-tested by test_shader_decls.py

SKY_PS = 0x33856d1d3ba64bb3  # FNV-1a 64 of the sky pixel shader bytecode, same across camp/desert/pond
NAMES = ('g_IntensityParam', 'g_AlbedoParam', 'g_BaseBoolParam', 'g_UvOffset', 'g_ShadowParam', 'g_MeshColor',
         'g_FogParam', 'g_SpParam', 'g_FogColor', 'g_lightColor', 'g_lightVec', 'g_CameraVec')
TEX_SLOTS = (0, 12, 17, 19)
FIELDS = {'draw': 14, 'state': 12, 'vcb': 4, 'pcb': 4, 'tex': 3, 'vb': 5, 'el': 5, 'buffer': 4}


def fnv1a64(data):
    h = 0xcbf29ce484222325
    for b in data:
        h = ((h ^ b) * 0x100000001b3) & 0xFFFFFFFFFFFFFFFF
    return h


def hostpath(p):
    """Manifests carry Windows paths (`Z:/home/...`); Z: is this machine's root in the replay prefixes."""
    if p[:3] == 'Z:/':
        return Path(p[2:])
    if len(p) > 2 and p[1:3] in (':/',):  # any other drive would silently resolve to a local path
        raise SystemExit(f'unsupported drive in capture path {p!r}; only Z: maps here')
    return Path(p)


def parse_manifest(path):
    """(header, draws). draw = {'draw', 'indices', 'viewport', 'ps_hash', 'state', 'cb', 'tex'}."""
    header, draws, current = {}, [], None
    for number, line in enumerate(Path(path).read_text().splitlines(), 1):
        w = line.split()
        if not w:
            continue
        kind = w[0]
        where = f'{path}:{number}'
        if kind in FIELDS and len(w) != FIELDS[kind]:
            raise SystemExit(f'{where}: malformed {kind} line, {len(w) - 1} fields, expected {FIELDS[kind] - 1}')
        if kind in ('shaders', 'cbblob'):
            header[kind] = line.split(None, 1)[1]
        elif kind == 'size':
            header['size'] = (int(w[1]), int(w[2]))
        elif kind == 'texture':
            header.setdefault('texture', {})[int(w[1])] = line.split(None, 2)[2]
        elif kind in ('replay', 'lights', 'buffer'):  # buffer ids are defined wherever they first appear
            continue
        elif kind == 'draw':
            current = {'draw': len(draws), 'indices': int(w[1]), 'viewport': (int(w[11]), int(w[12])),
                       'ps_hash': int(w[13]), 'state': None, 'cb': {}, 'tex': {}}
            draws.append(current)
        elif kind == 'end':
            if current is None:
                raise SystemExit(f'{where}: end without a draw block')
            current = None
        elif kind in ('state', 'vcb', 'pcb', 'tex', 'vb', 'el'):
            if current is None:
                raise SystemExit(f'{where}: {kind} line outside a draw block (before the first draw or after end)')
            if kind == 'state':
                current['state'] = [int(x) for x in w[1:]]
            elif kind == 'tex':
                slot = int(w[1])
                if slot in current['tex']:
                    raise SystemExit(f'{where}: duplicate tex slot {slot}')
                current['tex'][slot] = int(w[2])
            elif kind in ('vcb', 'pcb'):
                slot = int(w[1])
                if slot in current['cb'].get(kind, {}):
                    raise SystemExit(f'{where}: duplicate {kind} slot {slot}')
                current['cb'].setdefault(kind, {})[slot] = (int(w[2]), int(w[3]))
        else:
            raise SystemExit(f'{where}: unknown record {kind!r}')
    if 'cbblob' not in header:
        raise SystemExit(f'{path}: no cbblob line; not a packed scene manifest')
    return header, draws


def shader_blob(shaders, ps_hash):
    path = Path(shaders) / f'ps_{ps_hash}.dxbc'
    if not path.is_file():
        raise SystemExit(f'pixel shader ps_{ps_hash}.dxbc not in {shaders}')
    return path


def resolve(shader_path, bound):
    """Name -> (slot, register, byte offset, size) for every cbuffer member of this shader.

    The sky PS declares `PSParamBuffer1` twice (bind 1 and 2), so a name alone does not give the slot. Exact size
    matches are assigned first, then the remaining declarations only if exactly one unclaimed bind can hold them:
    bind 1 carries 112 bytes for the 64-byte declaration and bind 2 exactly 128 for the 128-byte one. Two binds of
    the claimed size are refused, never resolved by order.
    """
    cbuffers, resources = decls.declarations(decls.chunks(shader_path.read_bytes())['RDEF'][0])
    binds = {}
    for name, kind, bind, _count in resources:
        if kind == 'cbuffer':
            binds.setdefault(name, []).append(bind)
    assigned, pending = {}, []
    for index, (name, size, _variables) in enumerate(cbuffers):
        claimed = set(assigned.values())
        exact = [b for b in binds.get(name, []) if b not in claimed and bound.get(b) == size]
        if len(exact) == 1:
            assigned[index] = exact[0]
        elif len(exact) > 1:
            raise SystemExit(f'{shader_path.name}: {name} declares {size} bytes and binds {exact} carry exactly that; '
                             'ambiguous')
        else:
            pending.append(index)
    for index in pending:
        name, size, _variables = cbuffers[index]
        claimed = set(assigned.values())
        candidates = [b for b in binds.get(name, []) if b not in claimed]
        fits = [b for b in candidates if bound.get(b, 0) >= size]
        if len(fits) == 1:
            assigned[index] = fits[0]
        elif not any(bound.get(b) for b in candidates):
            assigned[index] = None  # no capture binds this buffer: nothing to place, and nothing to read
        else:
            raise SystemExit(f'{shader_path.name}: {name} declares {size} bytes; binds {fits} can hold it, need exactly '
                             'one')
    table, members = [], {}
    for index, (name, size, variables) in enumerate(cbuffers):
        slot = assigned.get(index)
        table.append({'name': name, 'slot': slot, 'size': size, 'bound': bound.get(slot)})
        if slot is None:
            continue
        for var, offset, var_size in variables:
            if var in members:
                raise SystemExit(f'{shader_path.name}: {var} declared in two constant buffers')
            members[var] = (slot, offset // 16, offset, var_size)
    return members, table


def dds_info(path):
    """Header only. None = no file; False = unreadable header (the two are different problems)."""
    try:
        head = Path(path).read_bytes()[:148]
    except OSError:
        return None
    if len(head) < 128 or head[:4] != b'DDS ':
        return False
    height, width = struct.unpack_from('<2I', head, 12)
    info = {'width': width, 'height': height, 'mips': struct.unpack_from('<I', head, 28)[0],
            'dxgi': None, 'array': 1, 'cube': False}
    if head[84:88] == b'DX10' and len(head) >= 148:
        info['dxgi'], _dim, misc, info['array'], _misc2 = struct.unpack_from('<5I', head, 128)
        info['cube'] = bool(misc & 0x4) and info['array'] % 6 == 0
    return info


def dump(manifest, cbs=None, shaders=None, ps=SKY_PS, names=NAMES, json_out=None):
    manifest = Path(manifest)
    header, draws = parse_manifest(manifest)
    blob = Path(cbs or hostpath(header['cbblob'])).read_bytes()
    root = Path(shaders or hostpath(header['shaders']))
    picked, selected = {}, []
    for draw in draws:
        path = shader_blob(root, draw['ps_hash'])
        code = picked.setdefault(draw['ps_hash'], (fnv1a64(path.read_bytes()), path.name))[0]
        if code == ps:
            selected.append((draw, path))
    if not selected:
        raise SystemExit(f'{manifest}: no draw uses ps {ps:#018x} (shader directory {root})')
    bound = {}  # widest binding per slot among the sky's own draws, which is what decides a duplicate name
    for draw, _path in selected:
        for slot, (_off, size) in draw['cb'].get('pcb', {}).items():
            bound[slot] = max(bound.get(slot, 0), size)
    members, table = resolve(selected[0][1], bound)
    records = []
    for draw, path in selected:
        values, registers = {}, {}
        for name in names:
            if name not in members:
                continue
            slot, reg, offset, size = members[name]
            where = draw['cb'].get('pcb', {}).get(slot)
            if where is None:
                raise SystemExit(f'{manifest}: draw {draw["draw"]}: {name} is declared in slot {slot}, which this draw '
                                 'does not bind')
            base, length = where
            if size % 4 or offset + size > length:
                raise SystemExit(f'draw {draw["draw"]}: {name} at {offset}+{size} outside pcb{slot} ({length} bytes)')
            values[name] = struct.unpack_from(f'<{size // 4}f', blob, base + offset)
            registers[name] = (slot, reg)
        textures = {}
        for slot in TEX_SLOTS:
            tid = draw['tex'].get(slot)
            entry = None if tid is None else {'id': tid, 'path': None}
            if tid is not None:
                declared = header.get('texture', {}).get(tid)
                if declared:
                    entry['path'] = str(hostpath(declared))
                    info = dds_info(hostpath(declared))
                    if info is None:
                        entry['unreadable'] = 'missing'
                    elif info is False:
                        entry['unreadable'] = 'header'
                    else:
                        entry.update(info)
            textures[f't{slot}'] = entry
        records.append({'draw': draw['draw'], 'indices': draw['indices'], 'viewport': draw['viewport'],
                        'ps_code': picked[draw['ps_hash']][0], 'ps_blob': path.name, 'state': draw['state'],
                        'registers': registers, 'values': values, 'textures': textures})
    out = {'manifest': str(manifest), 'shaders': str(root), 'ps': ps, 'draws_total': len(draws),
           'cbuffers': table, 'draws': records}
    if json_out:
        Path(json_out).parent.mkdir(parents=True, exist_ok=True)
        Path(json_out).write_text(json.dumps(out, indent=1, allow_nan=False) + '\n')
    return records


def fmt(values):
    return ' '.join(f'{v:.6g}' for v in values)


def main(argv):
    if len(argv) < 2 or argv[1] in ('-h', '--help'):
        sys.exit(__doc__)
    args = argv[1:]
    def opt(flag, default=None):
        return args[args.index(flag) + 1] if flag in args else default
    code = int(opt('--ps', hex(SKY_PS)), 16)
    try:
        records = dump(args[0], cbs=opt('--cbs'), shaders=opt('--shaders'), ps=code,
                       names=tuple(opt('--names').split(',')) if opt('--names') else NAMES, json_out=opt('--json'))
        header, draws = parse_manifest(Path(args[0]))
    except (OSError, ValueError, IndexError) as error:
        sys.exit(f'{args[0]}: {error}')
    print(f'{args[0]} ps {code:#018x} shader {records[0]["ps_blob"]} draws {len(records)}/{len(draws)} '
          f'viewport {records[0]["viewport"][0]}x{records[0]["viewport"][1]}')
    for r in records:
        print(f'draw {r["draw"]} indices {r["indices"]} state {" ".join(str(v) for v in r["state"])}')
        for name, (slot, reg) in r['registers'].items():
            print(f'  {name} b{slot}[{reg}] {fmt(r["values"][name])}')
        for slot, entry in r['textures'].items():
            if entry is None:
                print(f'  {slot} -')
            else:
                dims = f'{entry["width"]}x{entry["height"]}' if 'width' in entry else f'header {entry.get("unreadable")}'
                print(f'  {slot} tex_{entry["id"]} {dims} dxgi {entry["dxgi"]} mips {entry.get("mips")} '
                      f'array {entry["array"]}')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
