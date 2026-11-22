import io
import struct
import zipfile

from decompassets.n64 import zip_object_models as models


def _object():
    commands = struct.pack('>6I', 0x01003006, 0, 0x05000204, 0, 0xdf000000, 0)
    vertices = b''.join(struct.pack('>hhhHhhBBBB', x, y, 0, 0, 0, 0, 255, 255, 255, 255)
                        for x,y in ((0,0), (1,0), (0,1)))
    data = commands + vertices
    names = b'\0mesh_dl\0mesh_vtx\0'
    syms = bytes(16) + struct.pack('>IIIBBH', 1, 0, len(commands), 0x11, 0, 1)
    syms += struct.pack('>IIIBBH', 9, len(commands), len(vertices), 0x11, 0, 1)
    section_at = (64+len(data)+len(syms)+len(names)+3) & ~3
    ident = b'\x7fELF\x01\x02\x01' + bytes(9)
    header = struct.pack('>16sHHIIIIIHHHHHH', ident, 1, 8, 1, 0, 0, section_at, 0, 52, 0, 0, 40, 4, 0)
    body = header + bytes(64-len(header)) + data + syms + names
    body += bytes(section_at-len(body))
    sec = lambda *x: struct.pack('>10I', *x)
    body += bytes(40)
    body += sec(0,1,0,0,64,len(data),0,0,8,0)
    body += sec(0,2,0,0,64+len(data),len(syms),3,0,4,16)
    body += sec(0,3,0,0,64+len(data)+len(syms),len(names),0,0,1,0)
    return body


def test_zipped_elf_mesh_preview_and_bounds():
    obj = _object()
    assert len(models._objects(obj)) == 1
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_DEFLATED) as out:
        out.writestr('mesh.o',obj)
    image = bytes(64) + archive.getvalue() + bytes(16)
    assets = models.regions(image)
    assert len(assets) == 1
    assert assets[0]['meshes'][0]['triangles'] == 1
    result = models.preview(image,assets[0],{'mesh':0})
    assert result['vertices'][1] == (1,0,0)
    assert result['surfaces'][0]['indices'] == (0,1,2)
    assert models._objects(obj[:-1]) == []
