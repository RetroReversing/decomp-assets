"""Synthetic directory, compressed resources and local display-list previews."""
import struct

from decompassets.n64 import flag_lz_graphics as graphics

from .test_display_list_textures import build


def resource():
    image, _, _ = build(segment=2)
    data = bytearray(image[0x20000:0x20000+0x1000])
    end = data.find(bytes.fromhex('b800000000000000'))
    assert end > 0
    for at in range(0, end, 8):
        w0, w1 = struct.unpack_from('>II', data, at)
        if w0 == 0x04000c2f:
            struct.pack_into('>I', data, at, 0x01003006)
        elif w0 == 0xbf000000:
            struct.pack_into('>II', data, at, 0x05000204, 0)
    data[end:end+8] = bytes.fromhex('df00000000000000')
    return bytes(data[:end+8])


def packed(data):
    assert len(data) % 8 == 0
    return b'\x01' + len(data).to_bytes(3, 'big') + b''.join(
        b'\0'+data[i:i+8] for i in range(0, len(data), 8)) + b'\x80\0\0'


def directory(data):
    image = bytearray(0x1100)
    payload = packed(data)
    payload += bytes(-len(payload) % 16)
    for i in range(8):
        start = len(image)
        image.extend(payload)
        struct.pack_into('>II', image, 0x1000+8*i, start, len(image))
    return bytes(image)


def test_bounded_flag_stream_handles_copies_and_rejects_truncation():
    data = bytes.fromhex('0100000a 00 4142434445464748 c0 0102 0000')
    assert graphics.unpack(data) == b'ABCDEFGHGH'
    assert graphics.unpack(data[:-1]) is None
    assert graphics.unpack(bytes.fromhex('0100000a 80 0102')) is None


def test_directory_exposes_only_closed_local_mesh_and_texture():
    data = resource()
    meshes, textures = graphics.discover(data)
    assert len(meshes) == 1 and meshes[0]['triangles'] == 2
    assert len(textures) == 1
    image = directory(data)
    assets = graphics.regions(image)
    model = next(a for a in assets if a['layout'] == graphics.MODELS)
    texture = next(a for a in assets if a['layout'] == graphics.TEXTURES)
    assert graphics.preview(image, model, {})['triangles'] == 2
    assert graphics.preview(image, texture, {})['media'] == 'image'
    broken = bytearray(data)
    struct.pack_into('>I', broken, 0x10, 0x0200fff8)
    assert graphics.discover(broken) == ([], [])


def test_triangles_after_external_calls_need_another_local_vertex_load():
    data = bytearray(resource())
    start = int.from_bytes(data[0x10:0x14], 'big') & 0xffffff
    first_triangle = next(at for at in range(start, len(data), 8) if data[at] == 5)
    data[first_triangle:first_triangle] = bytes.fromhex('de00000003000000')
    meshes, _ = graphics.discover(data)
    assert len(meshes) == 1 and meshes[0]['triangles'] == 1


def test_partial_vertex_load_does_not_restore_other_slots_after_external_call():
    data = bytearray(resource())
    start = int.from_bytes(data[0x10:0x14], 'big') & 0xffffff
    triangles = [at for at in range(start, len(data), 8) if data[at] == 5]
    at = triangles[1]
    data[at:at] = bytes.fromhex('de00000003000000 01001002 02000020')
    meshes, _ = graphics.discover(data)
    assert len(meshes) == 1 and meshes[0]['triangles'] == 1


def test_ci4_indices_must_fit_the_loaded_palette(monkeypatch):
    original = graphics.display_lists._textures

    def partial_palette(data, group):
        for item in original(data, group):
            yield dict(item, palette_entries=1)

    monkeypatch.setattr(graphics.display_lists, '_textures', partial_palette)
    meshes, textures = graphics.discover(resource())
    assert meshes and not textures  # The second colour was never loaded into TMEM.
