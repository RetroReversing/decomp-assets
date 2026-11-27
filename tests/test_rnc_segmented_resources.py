"""A segmented model may keep its list, texture buffer and vertices in separate RNC blocks."""
import base64
import struct

from decompassets import n64
from decompassets.n64 import rnc_segmented_resources as assets

from .test_rnc import literal_block
from .test_rom_assets import pixels


def cmd(a, b=0):
    return struct.pack('>II', a, b)


def cartridge(*, swapped=False):
    palette = [cmd(0xfd100000, 0x0b000000), cmd(0xe8000000), cmd(0xf5000100, 0x07000000),
               cmd(0xe6000000), cmd(0xf0000000, (7 << 24) | (15 << 14)), cmd(0xe7000000)]
    tile = [cmd(0xfd500000, 0x0b000020), cmd(0xf5500000, 0x07000000), cmd(0xe6000000),
            cmd(0xf3000000, (7 << 24) | ((31 if swapped else 15) << 12) | (0 if swapped else 0x800)),
            cmd(0xe7000000), cmd(0xf5400200, 0), cmd(0xf2000000, ((60 if swapped else 28) << 12) | 28)]
    geometry = [cmd(0x01003006, 0x09000000), cmd(0x05000204), cmd(0xdf000000)]
    body = b''.join(palette+tile+geometry)
    commands = struct.pack('>I', len(body)) + b'\0\0\x08\x0b\x09\x04\x0a\0' + bytes(4) + body
    palette_bytes = bytes.fromhex('f80107c1')+bytes(28)
    if swapped:
        bitmap = (bytes([0x00]*4+[0x11]*4)+bytes([0x11]*4+[0x00]*4))*4
    else:
        bitmap = bytes([0x01, 0x10]*16)
    texture = struct.pack('>II', len(palette_bytes)+len(bitmap), 0) + palette_bytes + bitmap
    vertices = struct.pack('>HHI', 3, 0x200, 0)
    vertices += b''.join(struct.pack('>hhhHhhBBBB', x, y, 0, 0, 0, 0, 255, 255, 255, 255)
                         for x, y in ((0, 0), (1, 0), (0, 1)))
    first = literal_block(commands)
    second = literal_block(texture)
    third = literal_block(vertices)
    # The cartridge aligns packed records to two bytes; padding need not be zero.
    pad1 = b'\xff' if len(first) % 2 else b''
    pad2 = b'\xff' if (len(first)+len(pad1)+len(second)) % 2 else b''
    return first + pad1 + second + pad2 + third


def test_three_checked_streams_expose_texture_and_local_mesh():
    image = cartridge()
    found = assets.regions(image)
    model, texture = (next(a for a in found if a['kind'] == kind) for kind in ('3d model', 'image'))
    mesh = assets.preview(image, model, {})
    assert mesh['triangles'] == 1 and mesh['vertices'] == [(0, 0, 0), (1, 0, 0), (0, 1, 0)]
    preview = assets.preview(image, texture, {'texture': 0})
    assert pixels(base64.b64decode(preview['data_url'].split(',')[1]))[:8] == bytes([255, 0, 0, 255, 0, 255, 0, 255])
    # The console registry exposes both views and uses the same preview path.
    registered = [a for a in n64.regions(image) if a.get('layout') in (assets.MODEL, assets.TEXTURE)]
    assert {a['layout'] for a in registered} == {assets.MODEL, assets.TEXTURE}
    assert n64.preview(image, next(a for a in registered if a['layout'] == assets.MODEL), {})['triangles'] == 1


def test_missing_or_corrupt_companion_does_not_claim_an_asset():
    image = cartridge()
    assert not assets.regions(image[:-5])
    broken = bytearray(image)
    second = image.find(b'RNC', 4)
    broken[second+20] ^= 0xff
    assert not assets.regions(bytes(broken))


def test_texture_preview_unswaps_odd_rows():
    image = cartridge(swapped=True)
    texture = next(a for a in assets.regions(image) if a['kind'] == 'image')
    shown = assets.preview(image, texture, {'texture': 0})
    rgba = pixels(base64.b64decode(shown['data_url'].split(',')[1]))
    red, green = bytes([255, 0, 0, 255]), bytes([0, 255, 0, 255])
    assert rgba[:64] == red*8+green*8
    assert rgba[64:128] == red*8+green*8
