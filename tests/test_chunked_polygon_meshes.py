"""Indexed polygon previews require complete bounded vertices and faces."""
import struct
import zlib

from decompassets import n64
from decompassets.n64 import chunked_polygon_meshes, chunked_zlib


def payload():
    vertices = b''.join(struct.pack('>hhh',*v) for v in [(0,0,0),(10,0,0),(10,10,0),(0,10,0)])
    def face(a,b,c,d):
        return struct.pack('>II4H',0x21,0,a,b,c,d)+bytes(16)
    faces = face(0,1,2,3)+face(0,2,3,0xffff)
    descriptor = struct.pack('>8I',0,4,len(vertices),2,len(vertices),0,0,0)
    return vertices+faces+descriptor+bytes(8)


def container(raw):
    body = zlib.compress(raw)
    size = 12+len(body)
    padding = bytes(size & 1)
    return struct.pack('>III',size+len(padding),len(raw),len(body))+body+padding


def test_polygon_subset_preview_uses_bounded_signed_vertices():
    image = container(payload())
    blocks = chunked_zlib.regions(image)
    asset, = chunked_polygon_meshes.regions(image,blocks)
    result = n64.preview(image,asset,{'mesh':0})
    assert result['vertices'][2] == (10,10,0)
    assert result['triangles'] == 3
    assert len(result['surfaces']) == 3
    assert result['materials'] == []


def test_reject_out_of_range_vertices_and_unrelated_records():
    raw = bytearray(payload())
    raw[24+8:24+10] = (99).to_bytes(2,'big')
    assert not chunked_polygon_meshes._meshes(raw)
    raw = bytearray(payload())
    raw[24:28] = bytes(4)
    assert not chunked_polygon_meshes._meshes(raw)
    assert not chunked_polygon_meshes._meshes(payload()[:-20])
