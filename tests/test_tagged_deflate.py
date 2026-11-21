import struct
import zlib

from decompassets.n64 import preview, tagged_deflate


def _pack(data):
    codec = zlib.compressobj(wbits=-15)
    return (struct.pack('>I', len(data)) + len(data).to_bytes(3, 'little') + b'\x12'
            + codec.compress(data) + codec.flush())


def _archive(rows):
    directory = bytearray(struct.pack('>II', len(rows), 0))
    payload = bytearray()
    base = 8 + 40*len(rows)
    for name, kind, contents in rows:
        payload.extend(bytes(-(base+len(payload))%16))
        pointer = base+len(payload)
        resource = _pack(contents)
        directory.extend(struct.pack('>16s4s5I', name.encode(), kind, pointer, len(resource), 0, 2, len(resource)))
        payload.extend(resource)
    return bytes(directory+payload)


def _mesh():
    data = bytearray(176)
    header = [0]*25
    header[0:3] = [0x5d891456, 3, 1]
    header[8], header[10], header[11], header[22], header[23] = 100, 148, 160, 168, 172
    struct.pack_into('>25I', data, 0, *header)
    for index, (x,y) in enumerate(((0,0), (1,0), (0,1))):
        struct.pack_into('>3hH2h4B', data, 100+16*index, x,y,0, 0,0,0, 0,0,0,255)
    struct.pack_into('>6H', data, 148, 0,3,0,0,0,0)
    struct.pack_into('>3H', data, 160, 0,1,2)
    struct.pack_into('>H', data, 172, 3)
    return data


def test_tagged_media_uses_bounded_archive_sprites_and_meshes():
    texture = struct.pack('>II4H', 16, 18, 1, 1, 16, 0) + b'\x01\x23' + b'\xff\xff'*16
    sprite = struct.pack('>5I2H', 1,8,16,18,16,2,1) + b'\xff\xff'*2
    image = _archive([('texture', b'TXTR', texture), ('sprite', b'SPRT', sprite),
                      ('mesh', b'MESH', _mesh()), ('misc', b'ANIM', b'metadata'),
                      ('more', b'RAW ', b'extra')])
    tex, spr, mesh = tagged_deflate.regions(image)
    assert [(a['width'], a['height']) for a in (tex,spr)] == [(4,1),(2,1)]
    assert preview(image, tex, {})['media'] == preview(image, spr, {})['media'] == 'image'
    result = preview(image, mesh, {})
    assert result['vertices'] == [(0,0,0),(1,0,0),(0,1,0)]
    assert result['triangles'] == 1


def test_tagged_deflate_rejects_header_disagreement_and_bad_triangle():
    packed = _pack(b'metadata')
    assert tagged_deflate.unpack(packed) == b'metadata'
    assert tagged_deflate.unpack(packed[:-1]) is None
    assert tagged_deflate.unpack(packed[:4]+bytes(3)+packed[7:]) is None
    model = _mesh()
    struct.pack_into('>H', model, 164, 3)
    assert tagged_deflate._geometry(model) is None
