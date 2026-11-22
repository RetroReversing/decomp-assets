import base64
import struct

from decompassets.n64 import edl_indexed_textures as texture


def fixture():
    data = bytearray(0xe4)
    struct.pack_into('>IIHHIII',data,0,5,len(data),2,2,0x1c,16,0x3c)
    for i in range(2):
        struct.pack_into('>HHIIHH',data,0x28+16*i,2,8,0x0808,0,i,0)
    struct.pack_into('>I',data,0x50,12)
    for i in range(2):
        slot=0x54+4*i
        struct.pack_into('>I',data,slot,((0xa4+32*i-slot)<<8)|i)
        slot=0x5c+4*i
        struct.pack_into('>I',data,slot,0x64+32*i-slot)
    for i in range(32):
        struct.pack_into('>H',data,0x64+2*i,(i<<1)|1)
    data[0xa4:] = bytes(range(64))
    block = b'EDL\x80'+struct.pack('>II',len(data)+12,len(data))+data
    return bytes(data),block


def test_self_relative_indexed_textures_preview():
    data,block = fixture()
    items = texture.textures(data)
    assert len(items) == 2
    assert items[0]['preview_settings']['offset'] == 0xa4
    assert items[1]['preview_settings']['palette_offset'] == 0x84
    groups = texture.regions(block,{0:(0,len(block),len(data))},lambda:None)
    result = texture.preview(block,groups[0],{'texture':1})
    assert result['mime'] == 'image/png'
    assert base64.b64decode(result['data_url'].split(',')[1]).startswith(b'\x89PNG')


def test_invalid_palette_or_pointer_rejects_whole_pack():
    data,_ = fixture()
    bad = bytearray(data);struct.pack_into('>H',bad,0x34,2)
    assert not texture.textures(bad)
    bad = bytearray(data);struct.pack_into('>I',bad,0x54,0xffff0001)
    assert not texture.textures(bad)
