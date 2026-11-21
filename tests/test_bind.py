"""Synthetic BIND directories, PACK command streams and their previews."""

import base64
import struct

import pytest

from decompassets import formats, n64
from decompassets.n64 import bind, bind_textures


def pack(commands, size):
    stream = bytearray()
    remaining = 0
    for flags, payload in [('00', b''), *commands, ('11110', b'\0')]:
        for flag in flags:
            if not remaining:
                control = len(stream)
                stream.append(0)
                remaining = 8
            remaining -= 1
            stream[control] |= int(flag)<<remaining
        stream.extend(payload)
    return struct.pack('<4sII',b'PACK',size,len(stream))+stream


def archive(name, packed):
    size = (len(packed)+6)&~3
    return (struct.pack('<4sI32sII',b'BIND',1,name,48,size)
            +packed+bytes(size-len(packed)))


def test_pack_copies_overlapping_runs_and_checks_extent():
    data = pack([('0',b'A'), ('110',b'\0'), ('11100',b'\0'), ('11110',b'\x02\0')],16)
    assert bind.unpack(data) == b'A'*16
    with pytest.raises(formats.AssetError):
        bind.unpack(data[:-1])
    with pytest.raises(formats.AssetError,match='invalid copy'):
        bind.unpack(pack([('110',b'\0')],2))


def test_bind_tim_preserves_palette_order_and_dimensions():
    colors = [0, 0x001F, 0x03E0, 0x7C00]+[0]*12
    palette = struct.pack('<I4H16H',44,0,0,16,1,*colors)
    tim = struct.pack('<II',0x10,8)+palette+struct.pack('<I4H2B',14,0,0,1,1,0x21,0x03)
    data = archive(b'ICON.PAK',pack([('0',bytes([byte])) for byte in tim],len(tim)))
    asset, = [row for row in n64.regions(data) if row.get('layout') == bind_textures.LAYOUT]
    assert asset['preview_settings']['width'] == 4 and asset['preview_settings']['height'] == 1
    assert bind_textures._tim_pixels(bind_textures._tim(tim)) == (4,1,bytes((
        255,0,0,255, 0,255,0,255, 0,0,255,255, 0,0,0,0,
    )))
    result = n64.preview(data,asset,{})
    png = base64.b64decode(result['data_url'].split(',',1)[1])
    assert png.startswith(b'\x89PNG') and struct.unpack_from('>II',png,16) == (4,1)
    assert not list(bind.archives(data[:-1]))


def test_model_batches_resolve_local_vertex_indices():
    vertices = struct.pack('>12f',0,0,0,0, 1,0,0,0, 0,1,0,0)
    counts = struct.pack('>6I',1,1,0,1,1,0)
    material = struct.pack('>32s5I',b'ICON.TIM',0,0,0,1,0)
    batch = struct.pack('>5I',1,3,2,0,1)
    corners = b''.join(struct.pack('>I12x',index) for index in range(3))
    body = struct.pack('>32sI',b'TRIANGLE.A3D',3)+vertices+counts+material+batch+corners+bytes(18)
    data = struct.pack('>I',4+len(body))+body
    rom = archive(b'TRIANGLE.PAK',pack([('0',bytes([byte])) for byte in data],len(data)))
    asset, = [row for row in n64.regions(rom) if row.get('layout') == 'bind-a3d']
    model = n64.preview(rom,asset,{})
    assert model['vertices'] == [(0,0,0),(1,0,0),(0,1,0)]
    assert model['surfaces'][0]['indices'] == (2,0,1)
    bad = bytearray(data)
    struct.pack_into('>I',bad,len(data)-18-48,3)
    rom = archive(b'TRIANGLE.PAK',pack([('0',bytes([byte])) for byte in bad],len(bad)))
    assert not [row for row in n64.regions(rom) if row.get('layout') == 'bind-a3d']


def test_sprite_uses_its_unique_named_alpha_plane():
    color = bind.Member('SPRITE.PAK',0,100,2048)
    mask = bind.Member('SPRITEA.PAK',100,80,1024)
    assert bind_textures.sprite_pairs((color,mask)) == {color:mask,mask:color}
    duplicate = bind.Member('SPRITEA.PAK',180,80,1024)
    assert bind_textures.sprite_pairs((color,mask,duplicate)) == {}
