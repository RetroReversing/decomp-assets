import struct

from decompassets.n64 import fat_models, fat_textures


def fixture(monkeypatch):
    image = bytearray(0x400)
    struct.pack_into('>6H', image, 0x100, 0,0x8000,0x8000,24,64,2)
    image[0x200:0x218] = bytes.fromhex('0400103f06000000b100020600060400b800000000000000')
    for i,point in enumerate(((0,0,0),(1,0,0),(0,1,0),(1,1,0))):
        struct.pack_into('>3hH2h4B',image,0x300+i*16,*point,0,0,0,255,255,255,255)
    tables = [[(0x100,24,0),(0x200,23,0),(0x300,22,0)],[],[],[]]
    spans = [(0x20,24)]*4
    monkeypatch.setattr(fat_textures,'file_tables',lambda image,check:iter([(0,len(image),tables,[],spans)]))
    return image


def test_file_table_links_closed_mesh(monkeypatch):
    image = fixture(monkeypatch)
    groups = fat_models.regions(image)
    assert len(groups) == 1 and len(groups[0]['meshes']) == 1
    result = fat_models.preview(image,groups[0],{})
    assert len(result['vertices']) == 4 and len(result['surfaces']) == 2


def test_file_table_declines_invalid_vertex_reference(monkeypatch):
    image = fixture(monkeypatch)
    struct.pack_into('>H',image,0x104,0x8001)
    assert not fat_models.regions(image)
