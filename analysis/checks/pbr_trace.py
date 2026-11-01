#!/usr/bin/env python3
"""Which texture channel is albedo, metalness, gloss and normal, read from one pixel shader's disassembly.

Usage: pbr_trace.py <shader.asm> [...]       -> one JSON line per shader
       pbr_trace.py --dir <dir> [--json out]  -> every *.asm in dir, plus a coverage summary

Input is D3DDisassemble text (analysis/checks/dxbc_disasm.cpp). Method (analysis/PBR_MAPPING.md): forward provenance
over registers, component by component: every written component remembers which (texture slot, channel) pairs it was
computed from. Then the shader's own lighting maths names the roles:
  metalness  the F0 lerp           mad dst.xyz, M.c, base.xyz, l(0.03 | 0.08, ...)   -> source of M.c
  albedo     the same lerp's base   the 3-channel texture among base.xyz's sources
  gloss      GGX alpha             max a, x, l(1.00000005e-03) with x from (1 - g)^2  -> g's source, inverted
  normal     tangent-space map     sample then add ..., l(-0.5, -0.5, -0.5, 0)       -> main normal (RGB)
             detail map            sample then mad ..., l(2,2), l(-1,-1) on two lanes -> detail normal
A role that cannot be pinned to exactly one texture channel is left out rather than guessed.
"""
import json
import re
import sys
from pathlib import Path

LANES = 'xyzw'
MATERIAL_SLOTS = range(0, 8)  # 11 shadow, 12/19 fog LUTs, 13 depth, 14 dither, 17 screen AO, 18 cubes: never a material
OPENS = ('if_nz', 'if_z', 'loop', 'switch')
CLOSES = ('endif', 'endloop', 'endswitch')
NO_DEST = OPENS + CLOSES + ('else', 'discard_nz', 'discard_z', 'breakc_nz', 'breakc_z', 'break', 'continue',
                             'continuec_nz', 'continuec_z', 'case', 'default', 'retc_nz', 'retc_z')
REG = re.compile(r'^(-?)(\|?)([rvo])(\d+)\.([xyzw]+)\|?$')
TEX = re.compile(r'^t(\d+)\.([xyzw]{4})$')
CB = re.compile(r'^cb(\d+)\[(\d+)\]\.([xyzw]+)$')


def split_operands(text):
    out, depth, cur = [], 0, ''
    for ch in text:
        if ch == '(':
            depth += 1
        elif ch == ')':
            depth -= 1
        if ch == ',' and depth == 0:
            out.append(cur.strip())
            cur = ''
        else:
            cur += ch
    if cur.strip():
        out.append(cur.strip())
    return out


def parse(asm):
    """[(opcode, [operands])] for instructions only."""
    out = []
    for line in asm.splitlines():
        line = line.split('//')[0].strip()
        if not line or line.startswith(('dcl_', 'ps_', 'vs_')) or line == 'ret':
            continue
        m = re.match(r'(\S+)\s*(.*)', line)
        op = re.sub(r'\(.*', '', m.group(1))  # sample_indexable(texture2d) -> sample_indexable
        out.append((op, split_operands(m.group(2)), line))
    return out


def literal(text):
    m = re.match(r'l\((.*)\)$', text)
    if not m:
        return None
    out = []
    for x in m.group(1).split(','):
        x = x.strip()
        try:
            out.append(float(x))
        except ValueError:
            try:
                out.append(float(int(x, 0)))  # integer literals of bitwise ops, e.g. 0x80000000
            except ValueError:
                return None
    return out


def trace(asm):
    prov = {}      # ('r', 7, 'x') -> frozenset of (slot, channel)
    writer = {}    # ('r', 7, 'x') -> index of the instruction that last wrote it
    ins = parse(asm)
    found = {'metal': set(), 'albedo': set(), 'gloss': set(), 'normal': set(), 'detail': set(), 'cutout': set()}
    wrote = {}     # ('r', 6, 'x') -> (op, srcs, dest mask, depth) of the instruction that last wrote it
    found['uv'] = {}  # texture slot -> the UV transform of its first sample (uv_transform below)

    def uv_transform(coord):
        """Scale of a sample coordinate's two lanes, read back to the one instruction that wrote them: a vertex input
        times a constant (mad v, cb, cb / mul v, cb), an offset only (add v, cb), or the input itself. ('scale',
        cb slot, register, lanes) or ('none',) when the coordinate is the input untransformed; None when not simple."""
        m = REG.match(coord)
        if not m:
            return None
        _, _, kind, n, sw = m.groups()
        if kind == 'v':
            return ('none',)
        sw = (sw * 4)[:4] if len(sw) == 1 else sw
        found_scale = []
        for lane in sw[:2]:
            w = wrote.get((kind, int(n), lane))
            if not w or w[3] > 0:  # unwritten temp, or written inside a branch: not a simple transform
                return None
            op, srcs, dmask, _ = w
            k = dmask.index(lane)
            def at(operand):  # the source lane feeding destination lane k of a component-wise op
                mm = REG.match(operand) or CB.match(operand)
                if not mm:
                    return None
                s = mm.groups()[-1]
                s = (s * 4)[:4] if len(s) == 1 else s
                return mm, s[LANES.index(lane)] if len(s) == 4 else s[min(k, len(s) - 1)]
            if op in ('mad', 'mul') and len(srcs) >= 2:
                a, b = at(srcs[0]), at(srcs[1])
                if not a or not b:
                    return None
                vin = [x for x in (a, b) if REG.match(srcs[(a, b).index(x)]) and x[0].group(3) == 'v']
                cbs = [(srcs[i], x) for i, x in enumerate((a, b)) if CB.match(srcs[i])]
                if len(vin) != 1 or len(cbs) != 1:
                    return None
                cm = CB.match(cbs[0][0])
                found_scale.append((int(cm.group(1)), int(cm.group(2)), cbs[0][1][1]))
            elif op in ('add', 'mov') and srcs and REG.match(srcs[0]) and REG.match(srcs[0]).group(3) == 'v':
                found_scale.append(None)
            else:
                return None
        if found_scale == [None, None]:
            return ('none',)
        if None in found_scale or found_scale[0][:2] != found_scale[1][:2]:
            return None
        return ('scale', found_scale[0][0], found_scale[0][1], found_scale[0][2] + found_scale[1][2])

    def src_lanes(operand, dst_lanes):
        """Per destination lane, the source register lane it reads (component-wise ops)."""
        m = REG.match(operand)
        if not m:
            return None
        _, _, kind, n, sw = m.groups()
        sw = (sw * 4)[:4] if len(sw) == 1 else sw
        return kind, int(n), sw

    def sources(operand, lanes):
        r = src_lanes(operand, lanes)
        if not r:
            return frozenset()
        kind, n, sw = r
        out = set()
        for lane in lanes:
            c = sw[LANES.index(lane)] if len(sw) == 4 else sw[min(LANES.index(lane), len(sw) - 1)]
            out |= prov.get((kind, n, c), frozenset())
        return frozenset(out)

    def lane_source(operand, lane):
        return sources(operand, lane)

    depth = 0
    for i, (op, ops, line) in enumerate(ins):
        if op in OPENS:
            depth += 1
        elif op in CLOSES:
            depth = max(0, depth - 1)
        if op in NO_DEST or not ops:
            continue
        dst = REG.match(ops[0])
        if not dst:
            continue
        _, _, dkind, dn, dmask = dst.groups()
        dn = int(dn)
        srcs = ops[1:]
        new = {}
        if op.startswith('sample') or op.startswith('ld'):
            tex = next((TEX.match(s) for s in srcs if TEX.match(s)), None)
            if tex:
                slot, sw = int(tex.group(1)), tex.group(2)
                if slot not in found['uv'] and slot in MATERIAL_SLOTS:
                    found['uv'][slot] = uv_transform(srcs[0])
                # destination lane k takes the texture channel at the k-th position of the resource swizzle
                for lane in dmask:
                    new[lane] = frozenset({(slot, sw[LANES.index(lane)])}) if slot in MATERIAL_SLOTS else frozenset()
            else:
                for lane in dmask:
                    new[lane] = frozenset()
        elif op in ('dp2', 'dp3', 'dp4'):
            width = int(op[2])
            union = frozenset().union(*[sources(s, LANES[:width]) for s in srcs])
            for lane in dmask:
                new[lane] = union
        else:
            for lane in dmask:
                new[lane] = frozenset().union(*[lane_source(s, lane) for s in srcs])
        # role patterns, evaluated with the provenance *before* this write
        lits = [literal(s) for s in srcs]
        if op == 'mad' and len(srcs) == 3 and lits[2] and any(abs(v - 0.03) < 1e-6 or abs(v - 0.08) < 1e-6 for v in lits[2][:3]):
            m_src = REG.match(srcs[0])
            if m_src and len(set(m_src.group(5))) == 1:  # r7.y (Wine) or r7.yyyy (Microsoft): one lane
                found['metal'].add(lane_source(srcs[0], 'x'))
                found['albedo'].add(sources(srcs[1], 'xyz'))
        if op == 'max' and len(srcs) == 2 and lits[1] and abs(lits[1][0] - 1.00000005e-03) < 1e-9:
            found['gloss'].add(('alpha', sources(srcs[0], dmask)))
        # alpha test: lt x, src.w, l(threshold) feeding a discard -> the albedo texture's alpha
        if op == 'lt' and len(srcs) == 2 and lits[1] and REG.match(srcs[0]):
            found['cutout'].add(sources(srcs[0], 'x'))
        if op == 'add' and len(srcs) == 2 and lits[1] and lits[1][:3] == [-0.5, -0.5, -0.5]:
            found['normal'].add(sources(srcs[0], 'xyz'))
        if op == 'mad' and len(srcs) == 3 and lits[1] and lits[2]:
            two = [k for k, v in enumerate(lits[1]) if v == 2.0]
            if len(two) == 2 and all(lits[2][k] == -1.0 for k in two):
                found['detail'].add(sources(srcs[0], ''.join(LANES[k] for k in two)))
        for lane, s in new.items():
            # A write inside a branch may not happen: keep what the register held before as well.
            prov[(dkind, dn, lane)] = s | prov.get((dkind, dn, lane), frozenset()) if depth else s
            writer[(dkind, dn, lane)] = i
            wrote[(dkind, dn, lane)] = (op, srcs, dmask, depth)
    return found


def single(sets, width=1):
    """The one texture (slot, channels) every occurrence agrees on, or None."""
    texsets = {s for s in sets if s}
    if len(texsets) != 1:
        return None
    s = next(iter(texsets))
    slots = {slot for slot, _ in s}
    if len(slots) != 1 or len(s) != width:
        return None
    return {'slot': next(iter(slots)), 'channels': ''.join(sorted(c for _, c in s))}


def one_slot(sets, width, prefer=frozenset()):
    """The one slot supplying `width` channels to every occurrence (others may mix in), or the preferred slot on a tie."""
    picks = set()
    for s in (s for s in sets if s):
        by_slot = {}
        for slot, c in s:
            by_slot.setdefault(slot, set()).add(c)
        full = {slot for slot, cs in by_slot.items() if len(cs) >= width}
        if len(full) > 1 and full & prefer:
            full &= prefer
        if len(full) != 1:
            return None
        slot = next(iter(full))
        picks.add((slot, ''.join(sorted(by_slot[slot]))[:4]))
    if len(picks) != 1:
        return None
    slot, chans = next(iter(picks))
    return {'slot': slot, 'channels': chans if width < 3 else 'xyz'}


def roles(asm):
    f = trace(asm)
    out = {}
    if (m := single(f['metal'])):
        out['metal'] = m
    cutout = {slot for s in f['cutout'] for slot, c in s if c == 'w'}
    if (a := one_slot(f['albedo'], 3, frozenset(cutout))):
        out['albedo'] = a
    gloss = {s for _, s in f['gloss']}
    # alpha = (1 - g)^2: the gloss channel is the one texture channel alpha derives from, minus the metal channel
    cand = {s - frozenset({(out['metal']['slot'], out['metal']['channels'])}) if 'metal' in out else s for s in gloss}
    if (g := single(cand)):
        out['gloss'] = {**g, 'invert': True}
    if (n := single(f['normal'], 3)):
        out['normal'] = n
    if (d := one_slot(f['detail'], 2)):
        out['detail_normal'] = d
    # Texture repeat the game applies from a constant, per sampled slot (terrain layers: uv * cb1[5].xy). Reported for
    # every slot, because the albedo of a blended (terrain) shader is not a traced role and falls back to slot 0.
    scales = {slot: {'cb': uv[1], 'register': uv[2], 'lanes': uv[3]}
              for slot, uv in sorted(f['uv'].items()) if uv and uv[0] == 'scale'}
    if scales:
        out['uv_scale'] = scales
    return out


def main():
    args = sys.argv[1:]
    if args[:1] == ['--dir']:
        files = sorted(Path(args[1]).glob('*.asm'))
        result = {f.stem: roles(f.read_text(errors='replace')) for f in files}
        full = sum(1 for r in result.values() if {'albedo', 'metal', 'gloss', 'normal'} <= set(r))
        print(json.dumps({'shaders': len(result), 'full': full,
                          'by_role': {k: sum(1 for r in result.values() if k in r)
                                      for k in ('albedo', 'metal', 'gloss', 'normal', 'detail_normal')}}))
        if '--json' in args:
            Path(args[args.index('--json') + 1]).write_text(json.dumps(result, indent=1, sort_keys=True))
        return 0
    for a in args:
        print(json.dumps({'shader': Path(a).stem, **roles(Path(a).read_text(errors='replace'))}))
    return 0


if __name__ == '__main__':
    sys.exit(main())
