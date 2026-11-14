"""Recognize textures from the display lists that load them, in cartridges that store both uncompressed.

A display list's texture load names the image's address, format, size and dimensions, and its palette load
names the palette: everything a preview needs except where the address lies in the cartridge. Display lists
address their data in RAM (0x80xxxxxx) or through a segment (0x01xxxxxx-0x0Fxxxxxx), wherever the game loaded
the file, so each file's displacement (cartridge offset minus address) is worked out from the file itself:

- every vertex its lists load must land on vertices: sixteen bytes, the flag halfword zero, not all zero, and
- of the displacements that pass, the one under which most of its lists' starts are named by a pointer
  somewhere in the cartridge (a sub-list call, a table of lists) wins, and only if no other ties it.

A RAM displacement also has to put the lists inside the console's 8 MB of RAM. Files whose displacement stays
ambiguous keep no textures: a wrong one would show noise as a texture. The vertex loads of Fast3D, F3DEX and
F3DEX2 are read; the RDP's texture commands are the same in all of them.
"""
from __future__ import annotations

import struct
from array import array
from collections import Counter

MAX_FILE = 2 * 1024 * 1024
RDRAM = 8 * 1024 * 1024
CLUSTER_GAP = 0x1000
MAX_TEXTURE = 512 * 1024
MAX_TEXTURES = 20000

G_SETTIMG, G_SETTILE, G_LOADBLOCK, G_LOADTILE, G_LOADTLUT, G_SETTILESIZE = 0xFD, 0xF5, 0xF3, 0xF4, 0xF0, 0xF2
END_LISTS = (0xB8, 0xDF)
# Triangles (Fast3D/F3DEX, F3DEX2), texture rectangles and list ends: a tile set before them is used.
DRAWS = (0xBF, 0xB1, 0xB5, 0x05, 0x06, 0x07, 0xE4, 0xE5) + END_LISTS
FORMATS = {(0, 2): 'rgba5551-be', (0, 3): 'rgba8888', (2, 0): 'ci4', (2, 1): 'ci8',
           (3, 0): 'ia4', (3, 1): 'ia8', (3, 2): 'ia16', (4, 0): 'i4', (4, 1): 'i8'}
NAMES = {'rgba5551-be': 'RGBA16', 'rgba8888': 'RGBA32', 'ci4': 'CI4', 'ci8': 'CI8', 'ia4': 'IA4', 'ia8': 'IA8',
         'ia16': 'IA16', 'i4': 'I4', 'i8': 'I8'}
BITS = {0: 4, 1: 8, 2: 16, 3: 32}


def _space(word):
    """The address space of a display-list address: RAM (0x80), a segment (1-15), or None."""
    top = word >> 24
    if top in (0x80, 0xA0):return 0x80
    if 1 <= top <= 0x0F:return top
    return None


def _vertex_count(w0):
    """The vertex count of a Fast3D, F3DEX or F3DEX2 vertex load, or 0 when the word is not one."""
    cmd = w0 >> 24
    if cmd == 0x04:
        n = (w0 >> 10) & 0x3F
        if n and (w0 & 0x3FF) == n*16-1 and not (w0 >> 16) & 1:return n          # F3DEX
        n = ((w0 >> 20) & 0xF) + 1
        if (w0 & 0xFFFF) == n*16:return n                                        # Fast3D
    elif cmd == 0x01:
        n = (w0 >> 12) & 0xFF
        if n and not w0 & 1 and n <= ((w0 >> 1) & 0x7F) <= 64 and not (w0 >> 20) & 0xF:return n   # F3DEX2
    return 0


def _commands(image, check):
    """Each vertex load with an address, and each texture image followed by a tile and a load."""
    vertices, loads = [], []
    for at in range(0, len(image) - 72, 8):
        cmd = image[at]
        if cmd not in (0x04, 0x01, G_SETTIMG):continue
        if not at & 0xFFFF:check()
        w0, w1 = struct.unpack_from('>II', image, at)
        space = _space(w1)
        if space is None:continue
        if cmd == G_SETTIMG:
            ahead = image[at+8:at+72:8]
            if not (w0 >> 12) & 0x7F and G_SETTILE in ahead and any(c in ahead for c in (G_LOADBLOCK, G_LOADTILE, G_LOADTLUT)):
                loads.append(at)
        else:
            n = _vertex_count(w0)
            if n:vertices.append((at, space, w1 & 0xFFFFFF, n))
    return vertices, loads


def _files(vertices, loads):
    """Display lists close together in the cartridge are taken as one file, loaded at one address."""
    marks = sorted([(v[0], 0, v) for v in vertices] + [(at, 1, at) for at in loads])
    groups, last = [], None
    for at, kind, item in marks:
        if last is None or at - last > CLUSTER_GAP:groups.append(dict(start=at, vertices=[], loads=[]))
        groups[-1]['loads' if kind else 'vertices'].append(item);groups[-1]['end'] = at+8;last = at
    return [g for g in groups if g['loads']]


class _Evidence:
    """What displacements are judged by: where vertex runs start, and every address word in the cartridge."""

    def __init__(self, image, check):
        self.size = len(image)
        # run[k]: how many vertices in a row start at byte 8k.
        run = array('I', bytes(4*(len(image)//8 + 4)))
        for k in range(len(image)//8 - 2, -1, -1):
            if not k & 0x1FFF:check()
            at = 8*k
            if image[at+6] == 0 and image[at+7] == 0 and (any(image[at:at+6]) or any(image[at+8:at+16])):run[k] = run[k+2]+1
        self.run = run
        words = {}
        for index, (word,) in enumerate(struct.iter_unpack('>I', image[:len(image)//4*4])):
            if not index & 0x3FFF:check()
            space = _space(word)
            if space is not None:words.setdefault(space, set()).add(word & 0xFFFFFF)
        self.words = words

    def fits(self, refs, displacement):
        run = self.run
        for address, n in refs:
            at = address + displacement
            if at < 0 or at & 7 or at + 16*n > self.size or run[at >> 3] < n:return False
        return True

    def score(self, space, starts, displacement):
        words = self.words.get(space, ())
        return sum((start - displacement) in words for start in starts)


def _starts(image, group):
    """Where display lists begin in a file: its first command and each command after an end-of-list."""
    starts = [group['start']]
    for at in range(group['start'], group['end'], 8):
        if image[at] in END_LISTS and not any(image[at+1:at+8]):starts.append(at+8)
    return starts


def _ram_bounds(space, starts):
    """Displacements that keep every list start inside RAM: (lowest, highest), both inclusive."""
    if space != 0x80:return -(1 << 40), 1 << 40
    return max(starts) - RDRAM + 1, min(starts)


def _sample(items, count):
    step = max(1, len(items) // count)
    return items[::step][:count]


def _displacement(image, evidence, group, space, known, check):
    """The file's displacement for one address space, and why: 'shared', 'solved' or why there is none.

    Vertices alone rarely decide it: inside a large vertex array any shift by whole vertices still lands on
    vertices. They narrow the candidates (a sample of the loads first, all of them for the finalists), and
    the pointers to the file's list starts decide between them."""
    refs = sorted({(a, n) for _, s, a, n in group['vertices'] if s == space}, key=lambda r: (-r[1], r[0]))
    if len(refs) < 2:return None, 'too few vertex loads'
    starts = _starts(image, group)
    low, high = _ram_bounds(space, starts)
    for displacement in known.get(space, ()):
        if low <= displacement <= high and evidence.fits(refs, displacement) and evidence.score(space, starts, displacement):
            return displacement, 'shared'
    run, size = evidence.run, evidence.size
    address, n = refs[0]
    lo = max(-address, group['start'] - MAX_FILE - address, low)
    hi = min(size - 16*n - address, group['end'] + MAX_FILE - address, high + 1)
    first = lo + (-(lo + address)) % 8
    candidates = [d for d in range(first, hi, 8) if run[(address + d) >> 3] >= n]
    by_address = sorted(refs[1:])
    for address, n in (refs[1:9] + _sample(by_address, 16) + by_address[-1:]):
        check()
        candidates = [d for d in candidates if 0 <= address + d <= size - 16*n and not (address + d) & 7
                      and run[(address + d) >> 3] >= n]
        if not candidates:return None, 'no candidate'
    sampled = _sample(starts, 48)
    ranked = sorted(candidates, key=lambda d: -evidence.score(space, sampled, d))[:64]
    finalists = Counter({d: evidence.score(space, starts, d) for d in ranked if evidence.fits(refs, d)})
    (best, score), *rest = finalists.most_common(2) + [(None, -1)]
    if best is None:return None, 'no candidate'
    if score <= 0 or rest[0][1] == score:return None, 'ambiguous'
    return best, 'solved'


def _palette(found, palettes, palette_type):
    """Attach the palette the tile reads from TMEM, as far as one palette load filled it contiguously."""
    if found['fmt'] not in ('ci4', 'ci8'):return found
    entry = 256 + (16*found['palette'] if found['fmt'] == 'ci4' else 0)
    first = palettes.get(entry)
    if not first:return None
    count = 1
    while count < (16 if found['fmt'] == 'ci4' else 256) and palettes.get(entry+count, (None,))[0] == first[0]:count += 1
    return dict(found, palette_space=first[1], palette_address=first[2], palette_entries=count,
                palette_format='ia16' if palette_type == 3 else 'rgba5551-be')


def _textures(image, group):
    """Walk the file's commands as the RDP would, and yield each tile that is drawn from loaded texels.

    A tile is taken when something is drawn with it, so a palette loaded after the tile's size (as some games
    order it) is the one used. TMEM's palette half is tracked entry by entry: a smaller palette load replaces
    only the entries it covers."""
    timg = None;tiles = {};loaded = {};palettes = {};palette_type = 2;pending = [];loads = 0
    for at in range(group['start'], min(group['end'] + 0x100, len(image) - 8), 8):
        w0, w1 = struct.unpack_from('>II', image, at)
        cmd = w0 >> 24
        if cmd in DRAWS and pending:
            for found in pending:
                found = _palette(found, palettes, palette_type)
                if found:yield found
            pending = []
        if cmd == G_SETTIMG:
            space = _space(w1)
            timg = None if space is None else dict(fmt=(w0 >> 21) & 7, siz=(w0 >> 19) & 3, width=(w0 & 0xFFF)+1,
                                                   space=space, address=w1 & 0xFFFFFF, at=at)
        elif cmd == G_SETTILE:
            tiles[(w1 >> 24) & 7] = dict(fmt=(w0 >> 21) & 7, siz=(w0 >> 19) & 3, line=(w0 >> 9) & 0x1FF,
                                         tmem=w0 & 0x1FF, palette=(w1 >> 20) & 0xF)
        elif cmd in (G_LOADBLOCK, G_LOADTILE, G_LOADTLUT) and timg:
            tile = tiles.get((w1 >> 24) & 7)
            if not tile:continue
            if cmd == G_LOADTLUT:
                loads += 1
                for index in range(((w1 >> 14) & 0x3FF)+1):
                    palettes[tile['tmem']+index] = (loads, timg['space'], timg['address']+2*index)
            elif cmd == G_LOADBLOCK:
                if not w0 & 0xFFFFFF:loaded[tile['tmem']] = dict(timg, texels=((w1 >> 12) & 0xFFF)+1, block=True)
            elif not w0 & 0xFFFFFF:
                loaded[tile['tmem']] = dict(timg, texels=(((w1 >> 12) & 0xFFF)//4+1)*((w1 & 0xFFF)//4+1), block=False)
        elif cmd in (0xBA, 0xE3):
            # Set other mode H: only its texture-lookup-table type (bits 14-15) matters here.
            shift, length = ((w0 >> 8) & 0xFF, (w0 & 0xFF)) if cmd == 0xBA else (32-((w0 >> 8) & 0xFF)-((w0 & 0xFF)+1), (w0 & 0xFF)+1)
            if shift <= 14 and 16 <= shift+length:palette_type = (w1 >> 14) & 3
        elif cmd == G_SETTILESIZE:
            tile = tiles.get((w1 >> 24) & 7);source = tile and loaded.get(tile['tmem'])
            if not source:continue
            uls, ult, lrs, lrt = (w0 >> 12) & 0xFFF, w0 & 0xFFF, (w1 >> 12) & 0xFFF, w1 & 0xFFF
            if uls or ult or lrs & 3 or lrt & 3:continue
            fmt = FORMATS.get((tile['fmt'], tile['siz']))
            width, height = lrs//4+1, lrt//4+1
            if not fmt or width*height > 1024*1024:continue
            row = (width*BITS[tile['siz']]+7)//8
            if source['block']:
                if row*height > source['texels']*BITS[source['siz']]//8 + 8:continue
            elif source['width']*BITS[source['siz']] != width*BITS[tile['siz']]:continue
            pending.append(dict(fmt=fmt, width=width, height=height, bytes=row*height, space=source['space'],
                                address=source['address'], at=source['at'], palette=tile['palette']))


def regions(image, *, check=lambda: None, progress=lambda _: None):
    """Textures named by uncompressed display lists, in files whose load address can be worked out."""
    progress(dict(phase='Reading display lists', done=0, total=3))
    vertices, loads = _commands(image, check)
    files = _files(vertices, loads)
    if not files:return []
    progress(dict(phase='Reading display lists', done=1, total=3))
    evidence = _Evidence(image, check)
    progress(dict(phase='Placing display-list files', done=2, total=3))
    known, textures = {}, {}
    for index, group in enumerate(files):
        check()
        progress(dict(phase='Placing display-list files', done=index, total=len(files)))
        displacements = {}
        for space in {s for _, s, _, _ in group['vertices']}:
            displacement, _why = _displacement(image, evidence, group, space, known, check)
            if displacement is None:continue
            displacements[space] = displacement
            known.setdefault(space, [])
            if displacement not in known[space]:known[space].insert(0, displacement)
        for found in _textures(image, group):
            if found['space'] not in displacements:continue
            offset = found['address'] + displacements[found['space']]
            if not 0 <= offset <= len(image) - found['bytes'] or found['bytes'] > MAX_TEXTURE:continue
            palette = None
            if 'palette_address' in found:
                if found['palette_space'] not in displacements:continue
                palette = found['palette_address'] + displacements[found['palette_space']]
                if not 0 <= palette <= len(image) - 2*found['palette_entries']:continue
                if found['palette_entries'] < 256 and found['fmt'] == 'ci8' and max(image[offset:offset+found['bytes']]) >= found['palette_entries']:continue
            key = (offset, found['fmt'], found['width'], found['height'])
            entry = textures.setdefault(key, dict(found, offset=offset, palettes={}, lists=set()))
            if palette is not None:entry['palettes'].setdefault(palette, (found['palette_entries'], found['palette_format']))
            entry['lists'].add(found['at'])
            if len(textures) >= MAX_TEXTURES:break
    results = []
    for (offset, fmt, width, height), found in sorted(textures.items()):
        palettes = sorted(found['palettes'].items())
        if fmt in ('ci4', 'ci8') and not palettes:continue
        settings = dict(format=fmt, width=width, height=height, offset=offset, source='rom')
        if palettes:settings.update(palette_offset=palettes[0][0], palette_format=palettes[0][1][1])
        results.append(dict(offset=offset, size=found['bytes'], kind='image', confidence='inferred',
                            label=f'{NAMES[fmt]} {width}×{height} texture', layout='display-list',
                            preview_settings=settings, frames=1, palettes=len(palettes),
                            palette_entries=[entries for _, (entries, _) in palettes],
                            frame_offsets=[offset], palette_offsets=[at for at, _ in palettes],
                            levels=[dict(width=width, height=height, offset=0)],
                            display_lists=sorted(found['lists'])[:16],
                            reason=f'Loaded by {len(found["lists"])} display-list command(s), which give its format, size and '
                                   'palette. The file\'s load address was inferred from where its vertices and list pointers '
                                   'agree. Runtime use is not established.'))
    return results
