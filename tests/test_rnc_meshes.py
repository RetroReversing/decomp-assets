"""Synthetic polygon records and delta positions exercise the format without a game."""

import struct

import pytest

from decompassets import n64
from decompassets.n64 import models

from .test_rnc_textures import sum_block


def mesh():
    header=b'EMshV010'+struct.pack('>12H',1,4,4,1,1,1,1,0,0,0,0,0)
    polygon=struct.pack('>BBBH',4,0,0,0)
    corners=b''.join(struct.pack('>3H',i,0,0) for i in range(4))
    deltas=struct.pack('>12h',2,6,0, 5,0,0, 0,-6,0, -5,0,0)
    return header+polygon+corners+bytes(8+6+4)+deltas


@pytest.mark.parametrize('trailer',[b'',b'ATEX'+bytes(4)])
def test_emsh_scan_renders_the_indexed_quad(trailer):
    decoded=mesh()+trailer
    packed=sum_block(decoded)
    bank,=[asset for asset in n64.regions(bytes(48)+packed) if asset.get('layout')=='emsh-v010']
    assert bank['offset']==48 and bank['size']==len(packed)
    assert (bank['vertices'],bank['triangles'])==(4,2)
    result=n64.preview(decoded,bank,{'mesh':0})
    assert result['vertices']==[[2,6,0],[7,6,0],[7,0,0],[2,0,0]]
    assert [face['indices'] for face in result['surfaces']]==[[0,1,2],[0,2,3]]
    assert result['edges']==[(0,1),(0,2),(0,3),(1,2),(2,3)]


@pytest.mark.parametrize('offset',[9,21,32,36,38,40,42])
def test_emsh_rejects_invalid_counts_and_references(offset):
    raw=bytearray(mesh())
    raw[offset]=255
    assert not models.regions(sum_block(raw))


def test_emsh_rejects_unknown_trailer_and_damaged_rnc_sum():
    assert not models.regions(sum_block(mesh()+b'junk'+bytes(4)))
    packed=bytearray(sum_block(mesh()))
    packed[15]^=1
    assert not models.regions(packed)


def test_polygon_normal_does_not_select_the_first_corner():
    raw = bytearray(mesh())
    struct.pack_into('>H', raw, 8, 2)
    struct.pack_into('>H', raw, 12, 7)
    struct.pack_into('>H', raw, 20, 2)
    raw[37:37] = struct.pack('>BBBH', 3, 1, 0, 0)
    raw[66:66] = struct.pack('>9H', 1, 0, 0, 2, 0, 0, 3, 0, 0)
    _, faces = models.rnc_meshes.geometry(raw)
    assert [positions for positions, _, _ in faces] == [[0, 1, 2], [0, 2, 3], [1, 2, 3]]
    assert [texture for _, _, texture in faces] == [0, 0, 1]


def test_effect_tables_link_textures_and_refuse_ambiguous_candidates():
    from .test_rnc_textures import mixed_bank

    raw_mesh = bytearray(mesh())
    struct.pack_into('>H', raw_mesh, 18, 4)
    for index in range(4):
        struct.pack_into('>H', raw_mesh, 39+index*6, index)
    raw_mesh[75:75] = bytes(12)
    struct.pack_into('>8h', raw_mesh, 75, -16384, -16384, -15872, -16384, -15872, -15872, -16384, -15872)
    directory = bytearray()
    payload = bytearray()
    count = 8
    for raw in [bytes(raw_mesh), mixed_bank()]*count:
        record = sum_block(raw)
        directory.extend(struct.pack('>III', 12*count*2+len(payload),len(raw),sum(raw)))
        payload.extend(record+bytes(-len(record)%4)+b'END!')
    groups = b''.join(struct.pack('>Hxx', index*2) for index in range(count))
    meshes = b''.join(struct.pack('>IHHI',0x00100000+index*4,1,0,0x80000000+index*4) for index in range(count))
    textures = b''.join(struct.pack('>10xH',index*2+1) for index in range(count))
    image = bytes(directory+payload+groups+meshes+textures+b'\xff'*4)
    assets = n64.regions(image)
    linked = [asset for asset in assets if asset.get('emsh_texture_bank')]
    assert len(linked)==count
    result = n64.scene(image,linked[0],{},assets)
    assert result['materials'][0]['image'].startswith('data:image/png;base64,')
    assert result['surfaces'][0]['uv']==[[0,0],[1,0],[1,1]]
    assert not any(asset.get('emsh_texture_bank') for asset in n64.regions(image+textures))
