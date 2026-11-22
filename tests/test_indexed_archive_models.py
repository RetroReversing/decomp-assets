import struct

import pytest

from decompassets.n64.indexed_archive_models import meshes


def model():
    data=bytearray(72)
    for i,(x,y,z) in enumerate(((0,0,0),(10,0,0),(0,10,0))):
        struct.pack_into('>3hH2h4B',data,i*16,x,y,z,0,0,0,255,255,255,255)
    struct.pack_into('>II',data,48,0x01003006,0x03000000)
    struct.pack_into('>II',data,56,0x05000204,0)
    struct.pack_into('>II',data,64,0xdf000000,0)
    return data


@pytest.mark.parametrize('damage',[None,'space','vertices','indices','unterminated'])
def test_archive_model_requires_closed_list_and_resolved_geometry(damage):
    data=model()
    if damage=='space':data[52]=4
    if damage=='vertices':struct.pack_into('>I',data,52,0x03000040)
    if damage=='indices':struct.pack_into('>I',data,56,0x05000208)
    if damage=='unterminated':data[64]=0
    rows=meshes(data)
    assert len(rows)==(1 if damage is None else 0)
    if rows:assert (rows[0]['vertices'],rows[0]['triangles'])==(3,1)
