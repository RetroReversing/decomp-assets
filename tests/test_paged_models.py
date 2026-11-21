import struct

from decompassets import n64
from decompassets.n64 import paged_models


def _fixture(*, bad_face=False, damaged_page=False):
    header = struct.pack('>3H', 1, 3, 3)+bytes(54)
    face = struct.pack('>6H', 0,1,3 if bad_face else 2,0,1,2)+bytes(44)
    vertices = b''.join(struct.pack('>3fI', x,y,0,0) for x,y in [(0,0),(9,0),(0,9)])
    raw = header+face+vertices
    stream = b''.join(bytes([(1<<len(raw[at:at+8]))-1])+raw[at:at+8]
                      for at in range(0,len(raw),8))
    mesh = struct.pack('>I', len(raw))+stream
    mesh += bytes(-len(mesh)%2)
    image = bytearray(b'\0\3\1\0\0\0\0\x08')+bytearray(256*20+4)
    for number in range(4):
        start = len(image)
        entry = f'MESH{number+1}'.encode()
        body = mesh if number == 0 else bytes(8)
        struct.pack_into('>8sIII', image, 8+20*number, entry,2 if number == 0 else 3,len(body),start)
        image.extend(body)
    if damaged_page:
        struct.pack_into('>I', image, 8+256*20, 8)
    return bytes(image)


def test_paged_directory_supplies_exact_model_vertices_and_faces():
    image = _fixture()
    asset, = paged_models.regions(image)
    found = n64.preview(image,asset,{})
    assert found['vertices'] == [(0,0,0),(9,0,0),(0,9,0)]
    assert found['surfaces'][0]['indices'] == (0,1,2)


def test_paged_models_reject_broken_directory_links_and_face_indices():
    assert not paged_models.regions(_fixture(bad_face=True))
    assert not paged_models.regions(_fixture(damaged_page=True))
