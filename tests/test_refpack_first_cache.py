import struct

import pytest

from decompassets import formats
from decompassets.n64 import refpack_first_cache

from .test_shpn_images import literal


def fixture():
    vertices = b''.join(struct.pack('>hhhHhhI', i*2, (i%3)*7, i, 0, i, i, 0) for i in range(16))
    commands = (b'\0\x02\x10\0\x30\x04'
                + b'\x40\0\0\0\0\0\x40\x01\0\0\0\0\x40\x02\0\0\0\0'
                + b'\x20\x12\x22\x10\0\x01\x11\x04')
    node = bytearray(48)
    struct.pack_into('>II', node, 0, 3, 48+len(vertices)+len(commands))
    struct.pack_into('>H', node, 14, 16)
    def entry(size, offset, tag):
        return struct.pack('>II', size, offset)+tag.ljust(24,b'\0')
    tags = entry(36,8,b'@HEADER\0')+entry(len(vertices),48,b'@VERTICES\0')+entry(len(commands),48+len(vertices),b'@OPCODES\0')
    root = entry(4,8,b'@HEADER\0')+entry(0,0,b'@SEGMENTS\0')
    data = bytearray(bytes(24)+node+vertices+commands+tags+root)
    struct.pack_into('>II',data,0,2,len(data)-64)
    data[8:12] = b'\xbe\xef\0\0'
    return data


def test_first_batch_is_a_partial_model():
    data = fixture()
    image = literal(data)
    asset, = refpack_first_cache.regions(image)
    shown = refpack_first_cache.preview(image, asset, {})
    assert shown['triangles'] == 2
    assert shown['surfaces'][0]['indices'] == (0,1,2)
    assert 'Later cache reloads' in shown['note']


def test_unloaded_vertex_and_corrupt_section_are_rejected():
    data = fixture()
    op = 24+48+16*16
    data[op+6+6+1] = 0x10  # second vertex refers outside the first cache
    assert not refpack_first_cache.mesh(data)
    data = fixture()
    data[op+6] = 0x50  # another command is not proven to load a vertex slot
    assert not refpack_first_cache.mesh(data)
    data = fixture()
    tag = data.index(b'@VERTICES\0')
    data[tag-8:tag-4] = (0xffffffff).to_bytes(4,'big')
    assert not refpack_first_cache.mesh(data)


def test_preview_rechecks_source():
    image = literal(fixture())
    asset, = refpack_first_cache.regions(image)
    with pytest.raises(formats.AssetError):
        refpack_first_cache.preview(image[:-3], asset, {})
