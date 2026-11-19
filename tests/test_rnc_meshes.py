"""Synthetic polygon records and delta positions exercise the format without a game."""

import struct

import pytest

from decompassets import n64
from decompassets.n64 import models

from .test_rnc_textures import sum_block


def mesh():
    header=b'EMshV010'+struct.pack('>12H',1,4,4,0,1,1,1,0,0,0,0,0)
    polygon=struct.pack('>BBBH',4,0,0,0)
    corners=b''.join(struct.pack('>3H',i,0,0) for i in range(4))
    deltas=struct.pack('>12h',2,6,0, 5,0,0, 0,-6,0, -5,0,0)
    return header+polygon+corners+bytes(6+4)+deltas


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
