import io
import struct
import zipfile

from decompassets.n64 import zip_object_textures as textures


def _object():
    fields = [5,2,1,2,2,0,0,1,1,6,2,2,5,5,15,15]
    data = struct.pack('>16I',*fields)
    names = b'\0mesh_Textures\0'
    syms = bytes(16) + struct.pack('>IIIBBH',1,0,len(data),0x11,0,1)
    section_at = (64+len(data)+len(syms)+len(names)+3) & ~3
    ident = b'\x7fELF\x01\x02\x01' + bytes(9)
    header = struct.pack('>16sHHIIIIIHHHHHH',ident,1,8,1,0,0,section_at,0,52,0,0,40,4,0)
    body = header + bytes(64-len(header)) + data + syms + names
    body += bytes(section_at-len(body))
    sec = lambda *x: struct.pack('>10I',*x)
    return (body + bytes(40) + sec(0,1,0,0,64,len(data),0,0,8,0)
            + sec(0,2,0,0,64+len(data),len(syms),3,0,4,16)
            + sec(0,3,0,0,64+len(data)+len(syms),len(names),0,0,1,0))


def test_registry_resolves_archived_texture_and_palette():
    loader = bytes.fromhex('3c05000024a500003c030000246304008c4700048c46001800a328230c00000000e52823')
    image = bytearray(64)
    image[:len(loader)] = loader
    def row(ident,offset):
        return struct.pack('>8I',ident,offset,0,0x80001000,0x80002000,0,0,0)
    image.extend(row(5,0)+row(6,4)+row(7,516))
    image.extend(bytes(1024-len(image)))
    image.extend(bytes([0,1,2,3])+b'\xff\xff'*256+bytes(4))
    out = io.BytesIO()
    with zipfile.ZipFile(out,'w',compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('mesh.o',_object())
    image.extend(out.getvalue())
    found = textures.regions(bytes(image))
    assert len(found) == 1 and found[0]['texture_count'] == 1
    result = textures.preview(bytes(image),found[0],{'texture':0})
    assert result['media'] == 'image' and result['details']['width'] == 2
    image[0] = 0
    assert textures.regions(bytes(image)) == []
