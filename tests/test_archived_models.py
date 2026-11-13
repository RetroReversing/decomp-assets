"""Homemade triangle/quad models; no cartridge bytes or extracted assets."""
import struct

import pytest

from decompassets.formats import AssetError
from decompassets.n64 import archived_models as models

from .test_archived_textures import archive


def model():
    data=bytearray(136);data[:4]=b'PD3V';struct.pack_into('>I',data,32,2)
    struct.pack_into('>IHH',data,36,116,1,0)
    vertices=[(-20,-10,0),(20,-10,0),(20,10,0),(-20,10,0)]
    vertex_at=len(data);data.extend(b''.join(struct.pack('>hhh',*v) for v in vertices));poly=len(data)
    data.extend(bytes(12)+struct.pack('>3H',0,1,2)+bytes(8));data.extend(bytes(-len(data)%4));quad=len(data)
    data.extend(bytes(16)+struct.pack('>4H',0,1,2,3)+bytes(10));data.extend(bytes(-len(data)%4));table=len(data)
    data.extend(struct.pack('>IHHIHH',poly,1,6,quad,1,10));node=len(data);data.extend(bytes(108))
    data[node:node+4]=b'Demo';struct.pack_into('>II',data,node+80,vertex_at,poly)
    struct.pack_into('>H',data,node+100,2);struct.pack_into('>I',data,node+104,table)
    struct.pack_into('>IHH',data,44,node,1,8)
    return bytes(data),vertices


@pytest.mark.parametrize('offset,value',[(0,0),(32,255),(36,255),(42,1),(44,255),(48,255),(50,9),(172,255),(184,255)])
def test_corrupt_or_split_layouts_are_not_renderable(offset,value):
    raw,_=model();data=bytearray(raw);data[offset]=value
    assert models.layout(data) is None
    assert not models.regions(archive(data))


def test_truncation_bad_indices_overlaps_padding_and_crc():
    raw,_=model();node=int.from_bytes(raw[44:48],'big');table=int.from_bytes(raw[node+104:node+108],'big')
    for offset,value in [(node+80,0xffffffff),(node+104,table+4),(160+12,0xffff0001)]:
        bad=bytearray(raw);struct.pack_into('>I',bad,offset,value);assert models.layout(bad) is None
    assert models.layout(raw[:-1]) is None
    image=archive(raw);asset=models.regions(image)[0];bad=bytearray(image);bad[asset['archive']['payload']+3]^=255
    with pytest.raises(AssetError):models.preview(bad,asset,{})
    for choice in (-1,1,True,'bad'):
        with pytest.raises(AssetError,match='Mesh'):models.preview(image,asset,dict(mesh=choice))


def test_budget_and_cancellation(monkeypatch):
    raw,_=model();image=archive(raw)
    monkeypatch.setattr(models,'MAX_EXPANDED',1);assert not models.regions(image)
    def stop():raise RuntimeError('Stopped')
    with pytest.raises(RuntimeError,match='Stopped'):models.regions(image,check=stop)
