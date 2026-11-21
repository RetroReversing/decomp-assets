"""Paired gzip members must agree with their Fast3D indices and packing."""

import gzip
import io
import struct

import pytest

from decompassets.n64 import gzip_meshes


def member(name, payload):
    result = io.BytesIO()
    with gzip.GzipFile(filename=name, fileobj=result, mode='wb', mtime=0) as stream:
        stream.write(payload)
    return result.getvalue()


@pytest.mark.parametrize('segment,start', [(6, 0x50), (8, 0xc8), (9, 0x50)])
def test_gzip_geometry_pairs(segment, start):
    commands = struct.pack('>6I', 0x04200030, segment << 24, 0xbf000000, 0x00000a14, 0xb8000000, 0)
    end = start + 48
    geometry = bytearray(end)
    if segment == 6:
        struct.pack_into('>I', geometry, 0, 0x4c)
        struct.pack_into('>3I', geometry, 20, start, end, end)
    elif segment == 8:
        struct.pack_into('>3I', geometry, 24, 0xfffffffc, 1, end)
    else:
        struct.pack_into('>4I', geometry, 16, end, end+len(commands), end+24, end)
    struct.pack_into('>3h', geometry, start + 16, 3, -5, 7)
    image = member('test.raw', geometry) + member('test_dl.raw', commands)
    match, = gzip_meshes.regions(image)
    assert (match['vertices'], match['triangles']) == (3, 1)
    model = gzip_meshes.preview(image, match, {})
    assert model['vertices'][1] == (3, -5, 7)
    assert model['surfaces'][0]['indices'] == (0, 1, 2)
    assert gzip_meshes.regions(image[:-1]) == []
    assert gzip_meshes.regions(member('other.raw', geometry) + member('test_dl.raw', commands)) == []
    broken = bytearray(commands)
    broken[15] = 30
    assert gzip_meshes.regions(member('test.raw', geometry) + member('test_dl.raw', broken)) == []
