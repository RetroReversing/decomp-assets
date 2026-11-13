"""Source-assisted layout rules exercised only with homemade indexed textures."""
import base64
import struct

import pytest

from decompassets import formats as asset_formats
from decompassets import rnc
from decompassets.n64 import textures

from .test_rnc import literal_block
from .test_rom_assets import pixels


def indexed_set(blocks):
    head=(4*(len(blocks)+2)+7)//8*8
    offsets=[head]
    for block in blocks:offsets.append(offsets[-1]+len(block))
    return struct.pack('>'+str(len(offsets)+1)+'I',len(blocks),*offsets).ljust(head,b'\0')+b''.join(blocks)


def bank(fmt=1,frames=1):
    palette=bytes.fromhex('f80107c1003fffff')*(64 if fmt==0 else 4)
    bitmap=bytes([0x01] if fmt==0 else [0x01,0x23])*(64 if fmt==0 else 16)
    return indexed_set([bytes([fmt,1,3,3,255,0,0,0]),indexed_set([bitmap]*frames),indexed_set([palette])])


class Bits2:
    def __init__(self):self.data=bytearray();self.left=0;self.at=0
    def bit(self,value):
        if not self.left:self.at=len(self.data);self.data.append(0);self.left=8
        self.left-=1;self.data[self.at]|=value<<self.left
    def bits(self,values):
        for value in values:self.bit(int(value))
    def byte(self,value):self.data.append(value)
    def finish(self,output):
        self.bits('1111');self.byte(0);self.bit(0)
        payload=bytes(self.data)
        return b'RNC\2'+struct.pack('>IIHHBB',len(output),len(payload),rnc.crc16(output),rnc.crc16(payload),0,1)+payload


def literal2(output):
    w=Bits2();w.bits('00')
    for value in output:w.bit(0);w.byte(value)
    return w.finish(output)


@pytest.mark.parametrize('offset,value',[(24,2),(26,0),(29,9),(31,1),(40,0xff),(12,0xff)])
def test_malformed_tables_and_unsupported_layouts_are_not_images(offset,value):
    raw=bytearray(bank());raw[offset]=value
    assert textures.layout(raw) is None


def test_bad_compressed_checksums_and_output_caps_reject_assets(monkeypatch):
    raw=literal2(bank());broken=bytearray(raw);broken[-2]^=1
    assert not textures.regions(broken)
    with pytest.raises(rnc.RncError):rnc.unpack_m2(raw,max_output=32)
    with pytest.raises(rnc.RncError):rnc.unpack_m2(raw[:-1])
    monkeypatch.setattr(textures,'MAX_EXPANDED',32)
    assert not textures.regions(raw)


def test_method2_overlap_long_literals_and_bad_distances():
    w=Bits2();w.bits('000');w.byte(97);w.bits('110');w.byte(0)
    assert rnc.unpack_m2(w.finish(b'aaa'))==b'aaa'
    w=Bits2();w.bits('00101110000')
    for value in range(12):w.byte(value)
    assert rnc.unpack_m2(w.finish(bytes(range(12))))==bytes(range(12))
    w=Bits2();w.bits('00110');w.byte(0)
    with pytest.raises(rnc.RncError,match='back-reference'):rnc.unpack_m2(w.finish(b'aa'))


def test_native_recognition_checks_stop_and_does_not_mutate_inputs():
    image=literal2(bank());before=bytes(image)
    def stop():raise RuntimeError('stopped')
    with pytest.raises(RuntimeError,match='stopped'):textures.regions(image,check=stop)
    assert image==before


def test_jpeg_frame_and_scan_headers_must_agree():
    def segment(marker,payload):return bytes([255,marker])+struct.pack('>H',len(payload)+2)+payload
    frame=bytes.fromhex('080008000801011100')
    scan=bytes.fromhex('010100003f00')
    image=b'\xff\xd8'+segment(0xc0,frame)+segment(0xda,scan)+b'\x12\xff\xd9'
    assert asset_formats.identify(image)['width']==8
    wrong=scan[:1]+b'\2'+scan[2:]
    with pytest.raises(asset_formats.AssetError,match='scan header'):asset_formats.identify(b'\xff\xd8'+segment(0xc0,frame)+segment(0xda,wrong)+b'\xff\xd9')
    with pytest.raises(asset_formats.AssetError,match='frame header'):asset_formats.identify(b'\xff\xd8'+segment(0xc0,frame[:-1])+segment(0xda,scan)+b'\xff\xd9')


def mixed_bank():
    short=bytes.fromhex('07c1')*16;full=bytes.fromhex('f801')*256
    return indexed_set([bytes([0,1,3,3,255,0,0,0]),indexed_set([bytes([1])*64,bytes([200])*64]),indexed_set([short,full])])


@pytest.mark.parametrize('pack',[lambda x:x,literal_block,literal2])
def test_ci8_mixed_palettes_are_bounded_and_follow_frame_pairing(pack):
    raw=mixed_bank();payload=pack(raw);image=bytes(31)+payload
    found=textures.regions(image);assert len(found)==1
    asset=found[0];assert asset['palette_entries']==[16,256]
    data=textures.decode(payload)[0] if payload!=raw else image
    for frame,color in [(0,bytes([0,255,0,255])),(1,bytes([255,0,0,255]))]:
        result=textures.preview(data,asset,dict(frame=frame))
        assert pixels(base64.b64decode(result['data_url'].split(',')[1]))==color*64
        assert result['details']['palette_colours']==(16 if frame==0 else 256)
    with pytest.raises(asset_formats.AssetError,match='matching palette'):textures.preview(data,asset,dict(frame=1,palette=0))
    # Native short palettes also work at EOF, without borrowing bytes from another block.
    short_only=indexed_set([bytes([0,1,3,3,255,0,0,0]),indexed_set([bytes([15])*64]),indexed_set([bytes.fromhex('07c1')*16])])
    short_asset=textures.regions(short_only)[0]
    assert textures.preview(short_only,short_asset,{})['details']['palette_colours']==16


def test_ci8_rejects_missing_colours_and_unsupported_palette_extents():
    raw=mixed_bank();layout=textures.bank_layout(raw)
    for offset in (layout['frame_offsets'][0],):
        broken=bytearray(raw);broken[offset]=16;assert textures.bank_layout(broken) is None
    bad=indexed_set([bytes([0,1,3,3,255,0,0,0]),indexed_set([bytes(64)]),indexed_set([bytes(64)])])
    assert textures.bank_layout(bad) is None
