"""Homemade indexed meshes exercise byte planes and the rotating vertex cache."""
import struct

import pytest

from decompassets.formats import AssetError
from decompassets.n64 import models

from .test_native_textures import indexed_set, literal2


def stream(width,values):
    raw=struct.pack('>II',width,len(values))+b''.join(values)
    return raw.ljust((len(raw)+7)//8*8,b'\0')


def mesh(count=3,commands=None):
    points=[(i*7-200,(i*i%13)*30-10,100-(i%7)*29) for i in range(count)]
    rows=[struct.pack('>hhhHhh4B',*v,0,0,0,255,255,255,255) for v in points]
    planes=bytes(rows[i][column] for column in range(16) for i in range(count))
    vertices=(struct.pack('>II',16,count)+planes).ljust((8+len(planes)+7)//8*8,b'\0')
    commands=commands if commands is not None else [0x8000|0|(1<<5)|(2<<10)]
    poly=stream(2,[struct.pack('>H',word) for word in commands])
    return indexed_set([bytes(24),poly,vertices]),points


def container(*sections):
    node=indexed_set([stream(0,[]),stream(4,[bytes(4)]),indexed_set([indexed_set(list(sections))])])
    return indexed_set([bytes(8),indexed_set([node])])


def test_cache_replacement_uses_retained_and_reloaded_halves():
    word=lambda a,b,c:0x8000|a|(b<<5)|(c<<10)
    section,_=mesh(49,[word(0,1,31),word(0,16,31),word(0,16,31)])
    raw=container(section);asset=models.regions(raw)[0];preview=models.preview(raw,asset,{})
    assert preview['edges']==[(0,1),(0,31),(1,31),(16,31),(16,32),(31,32),(31,48),(32,48)]
    assert preview['triangles']==3


@pytest.mark.parametrize('count,commands',[(3,[0x8000|(3<<10)]),(33,[0x8000]),(3,[0]),(3,[0x8000,0x8000]),(0,[])])
def test_invalid_or_incomplete_cache_streams_are_not_models(count,commands):
    section,_=mesh(count,commands);assert not models.regions(container(section))


def test_corrupt_tables_stream_extents_and_crc_are_not_models():
    section,_=mesh();raw=container(section)
    for offset in (4,12,28):
        broken=bytearray(raw)
        broken[offset]=255;assert not models.regions(broken)
    payload=bytearray(literal2(raw));payload[-2]^=1
    assert not models.regions(payload)
    assert not models.regions(raw[:-1])
    assert not models.regions(bytes(24)*300)


def test_indices_limits_and_cancellation(monkeypatch):
    section,_=mesh();raw=container(section);asset=models.regions(raw)[0]
    for value in (-1,1,'garbage',True):
        with pytest.raises(AssetError,match='Mesh'):models.preview(raw,asset,dict(mesh=value))
    monkeypatch.setattr(models,'MAX_SECTIONS',0)
    assert not models.regions(raw)
    def stop():raise RuntimeError('stop')
    with pytest.raises(RuntimeError,match='stop'):models.regions(raw,check=stop)
    monkeypatch.setattr(models,'MAX_CANDIDATES',0);assert not models.regions(raw)


def test_stream_widths_counts_and_total_decode_budget_are_checked(monkeypatch):
    section,_=mesh();raw=container(section)
    root=models.blocks(raw,(0,len(raw)),2)
    node=models.blocks(raw,root[1])[0]
    part=models.blocks(raw,models.blocks(raw,node,3)[2])[0]
    material,poly,vertices=models.blocks(raw,models.blocks(raw,part)[0],3)
    for offset,value in [(poly[0],4),(poly[0]+4,8193),(vertices[0],8),(vertices[0]+4,4097)]:
        broken=bytearray(raw);struct.pack_into('>I',broken,offset,value)
        assert not models.regions(broken)
    monkeypatch.setattr(models,'MAX_EXPANDED',len(raw)-1)
    assert not models.regions(literal2(raw))
    monkeypatch.setattr(models,'MAX_BYTES',len(raw)-1)
    assert not models.regions(raw)
