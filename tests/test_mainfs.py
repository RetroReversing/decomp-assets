"""A main filesystem of packed files with image packs and FORM models: homemade data only."""
import base64
import struct

from decompassets import n64
from decompassets.n64 import mainfs

from .test_rom_assets import pixels

RED, GREEN = bytes.fromhex('f801'), bytes.fromhex('07c1')


def lz(raw):
    """Type 1, literals only: a flag byte of eight set bits before each eight bytes."""
    return b''.join(b'\xff' + raw[at:at+8] for at in range(0, len(raw), 8))


def slide(raw):
    """Types 2-4, literals only: a flag word of 32 set bits before each 32 bytes."""
    return b''.join(b'\xff\xff\xff\xff' + raw[at:at+32] for at in range(0, len(raw), 32))


def runs(raw):
    """Type 5: copies of up to 127 bytes."""
    return b''.join(bytes([0x80 | len(raw[at:at+127])]) + raw[at:at+127] for at in range(0, len(raw), 127))


def image_pack(images, bits, palette=b''):
    entries = 0x20;first = entries + 12*len(images)
    body, table, at = b'', b'', first
    for width, height, texels in images:
        table += struct.pack('>IHHhh', at, width, height, 0, 0);body += texels;at += len(texels)
    header = struct.pack('>4IHHHHBBH', entries, first, first, at if palette else at, len(images), 1,
                         sum(w for w, _, _ in images), sum(h for _, h, _ in images), 0, bits, 0)
    return header + bytes(entries - len(header)) + table + body + palette


def form(chunks):
    body = b'HBINMODE' + struct.pack('>I', 0)
    for tag, data in chunks:body += tag + struct.pack('>I', len(data)) + data + bytes(len(data) & 1)
    return b'FORM' + struct.pack('>I', len(body)) + body


def filesystem(directories):
    """directories: lists of (packing type, raw data, packed data)."""
    head = 4 + 4*len(directories)
    blobs, offsets, at = [], [], head
    for files in directories:
        table = 4 + 4*len(files);parts, entries, inner = [], [], table
        for kind, raw, packed in files:
            item = struct.pack('>II', len(raw), kind) + packed
            item += bytes(-len(item) % 4)
            entries.append(inner);parts.append(item);inner += len(item)
        blob = struct.pack(f'>I{len(files)}I', len(files), *entries) + b''.join(parts)
        offsets.append(at);blobs.append(blob);at += len(blob)
    return struct.pack(f'>I{len(directories)}I', len(directories), *offsets) + b''.join(blobs)


def build():
    indexed = image_pack([(4, 2, bytes([0x01, 0x10] * 2))], 4, RED + GREEN)               # two colours, padded
    grey = image_pack([(8, 2, bytes([0xF0] * 4 + [0x0F] * 4))], 4)
    model = form([(b'PAL1', struct.pack('>HH', 7, 2) + GREEN + RED),
                  (b'BMP1', struct.pack('>HHBHHH', 0, 0x128, 0, 4, 2, 7) + bytes(4) + struct.pack('>H', 8) + bytes([1, 0] * 4))])
    directories = [[(1, indexed, lz(indexed)), (0, b'not an image at all', b'not an image at all')], [],
                   [(5, model, runs(model)), (2, grey, slide(grey))]]
    return bytes(0x40) + filesystem(directories)


def test_filesystem_images_are_found_in_packs_and_models():
    image = build()
    root, files = mainfs.find(image)
    assert root == 0x40 and [(d, i) for d, i, _ in files] == [(0, 0), (0, 1), (2, 0), (2, 1)]
    found = mainfs.regions(image)
    assert [(a['directory'], a['file'], a['packing'], [t['preview_settings']['format'] for t in a['textures']]) for a in found] == [
        (0, 0, 1, ['ci4']), (2, 0, 5, ['ci8']), (2, 1, 2, ['i4'])]
    assert [a['layout'] for a in n64.regions(image) if a.get('layout') == 'mainfs'] == ['mainfs'] * 3
    shown = [pixels(base64.b64decode(n64.preview(image, a, {})['data_url'].split(',')[1])) for a in found]
    assert shown[0][:8] == bytes([255, 0, 0, 255, 0, 255, 0, 255])          # palette index 0 red, 1 green
    assert shown[1][:8] == bytes([255, 0, 0, 255, 0, 255, 0, 255])          # PAL1 number 7: index 1 red, 0 green
    assert shown[2][:4] == bytes([255, 255, 255, 255]) and shown[2][4:8] == bytes([0, 0, 0, 255])


def test_tables_and_packs_that_do_not_hold_together_are_left_out():
    image = bytearray(build())
    struct.pack_into('>I', image, 0x44, 0x14)                               # the first directory's offset is wrong
    assert mainfs.find(bytes(image)) == (None, None)
    pack = image_pack([(64, 64, bytes(16))], 8)                              # its image runs past the file
    assert mainfs.pack_images(pack) is None
    assert mainfs.form_images(form([(b'BMP1', struct.pack('>HHBHHH', 0, 0x128, 0, 4, 2, 9) + bytes(6))])) is None
