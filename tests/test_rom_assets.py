"""Homemade pixels, PCM and machine instructions exercise asset evidence end to end."""
import base64
import gzip
import io
import struct
import wave
import zlib

import pytest

from decompassets import formats as asset_formats
from decompassets.formats import AssetError


def words(*values,big=True):return struct.pack(('>' if big else '<')+str(len(values))+'I',*values)


def lui(reg,value):return 15<<26 | reg<<16 | value>>16


def addiu(reg,base,value):return 9<<26 | base<<21 | reg<<16 | value&0xffff


def jal(address):return 3<<26 | (address>>2)&0x3ffffff


def sw(reg,base,offset):return 0x2b<<26 | base<<21 | reg<<16 | offset&0xffff


def pixels(payload):
    at=8;raw=bytearray();width=height=0
    while at<len(payload):
        length=int.from_bytes(payload[at:at+4],'big');kind=payload[at+4:at+8]
        if kind==b'IHDR':width,height=struct.unpack('>II',payload[at+8:at+16])
        if kind==b'IDAT':raw.extend(payload[at+8:at+8+length])
        at+=length+12
    decoded=zlib.decompress(raw)
    return b''.join(decoded[y*(width*4+1)+1:(y+1)*(width*4+1)] for y in range(height))


@pytest.mark.parametrize('fmt,raw,expected',[
    ('rgba5551-be',b'\xf8\x01',bytes([255,0,0,255])),('rgb565-le',b'\xe0\x07',bytes([0,255,0,255])),
    ('rgba8888',b'\x01\x02\x03\x04',b'\x01\x02\x03\x04'),('ia4',b'\xf0',bytes([255,255,255,255])),
    ('ia8',b'\xa5',bytes([170,170,170,85])),('ia16',b'\x34\x56',bytes([52,52,52,86])),
    ('i4',b'\x80',bytes([136,136,136,255])),('i8',b'\x7f',bytes([127,127,127,255])),
    ('palette-rgba5551',b'\x00\x3f',bytes([0,0,255,255])),
])
def test_texture_and_palette_pixels_are_exact(fmt,raw,expected):
    png,details=asset_formats.texture(raw,dict(format=fmt,width=1,height=1))
    assert pixels(png)==expected and details['bytes']==len(raw)


def test_indexed_texture_uses_explicit_palette_and_odd_rows_are_byte_padded():
    raw=b'\x10\x20'+b'\x00\x01\xf8\x01\x07\xc1'+bytes(26)
    png,_=asset_formats.texture(raw,dict(format='ci4',width=1,height=2,palette_offset=2))
    assert pixels(png)==bytes([255,0,0,255,0,255,0,255])
    with pytest.raises(AssetError,match='truncated'):asset_formats.texture(b'\0',dict(format='ci8',width=1,height=1,palette_offset=1))


@pytest.mark.parametrize('fmt,raw,expected,width',[('pcm-s16be',b'\x12\x34\xfe\xdc',b'\x34\x12\xdc\xfe',2),('pcm-u8',b'\x00\x80\xff',b'\x00\x80\xff',1)])
def test_pcm_audio_has_correct_sample_order_and_wav_metadata(fmt,raw,expected,width):
    payload,details=asset_formats.pcm(raw,dict(format=fmt,length=len(raw),rate=22050,channels=1))
    with wave.open(io.BytesIO(payload)) as f:
        assert f.getsampwidth()==width and f.getframerate()==22050
        assert f.readframes(100)==expected
    assert asset_formats.identify(payload)['format']=='PCM WAVE'


def test_recognized_png_and_wav_have_validated_extents_and_reject_corruption():
    image,_=asset_formats.texture(b'\xff\0\0\xff',dict(format='rgba8888',width=1,height=1))
    result=asset_formats.preview(image+b'trailing',dict(format='auto'))
    assert base64.b64decode(result['data_url'].split(',')[1])==image
    assert result['details']['size']==len(image)
    bad=bytearray(image);bad[29]^=1
    with pytest.raises(AssetError,match='checksum'):asset_formats.identify(bytes(bad))
    with pytest.raises(AssetError):asset_formats.identify(image[:-1])


@pytest.mark.parametrize('codec',['zlib','gzip','Yaz0','MIO0','Yay0'])
def test_bounded_decompression_supplies_asset_bytes(codec):
    raw=b'asset'
    if codec=='zlib':packed=zlib.compress(raw)
    elif codec=='gzip':packed=gzip.compress(raw)
    elif codec=='Yaz0':packed=b'Yaz0'+struct.pack('>I',len(raw))+bytes(8)+b'\xf8'+raw
    else:
        mask=b'\xf8' if codec=='MIO0' else b'\xf8\0\0\0'
        packed=codec.encode()+struct.pack('>III',len(raw),16+len(mask),16+len(mask))+mask+raw
    assert asset_formats.unpack(packed)==(raw,codec)
    with pytest.raises(AssetError):asset_formats.unpack(packed[:10])


def test_bounds_and_format_errors_are_actionable():
    for options in (dict(format='i8',width=2048,height=2048),dict(format='i8',width=True,height=1),dict(format='invalid')):
        with pytest.raises(AssetError):asset_formats.preview(bytes(32),options)
    with pytest.raises(AssetError,match='whole sample'):asset_formats.pcm(bytes(3),dict(format='pcm-s16le',length=3))
    with pytest.raises(AssetError,match='30 seconds'):asset_formats.pcm(bytes(64000),dict(format='pcm-s16le',length=64000,rate=1000))
    with pytest.raises(AssetError,match='4 MiB'):asset_formats.unpack(zlib.compress(bytes(asset_formats.MAX_BYTES+1)))


def test_standard_mono_vagp_decodes_nibbles_and_rejects_variants():
    header=bytearray(48);header[:4]=b'VAGp';header[12:16]=struct.pack('>I',16);header[16:20]=struct.pack('>I',22050)
    packed=bytes(header)+b'\x0c\x01'+b'\x21'*14
    result=asset_formats.preview(packed,dict(format='auto'))
    with wave.open(io.BytesIO(base64.b64decode(result['data_url'].split(',')[1]))) as audio:
        assert audio.readframes(28)==struct.pack('<28h',*([1,2]*14))
    assert asset_formats.identify(packed)['size']==64
    bad=bytearray(packed);bad[48]=0xf0
    with pytest.raises(AssetError,match='predictor'):asset_formats.preview(bytes(bad),dict(format='auto'))
    bad=bytearray(packed);bad[31]=2
    with pytest.raises(AssetError,match='custom channel'):asset_formats.preview(bytes(bad),dict(format='auto'))


def test_decompression_matches_independent_codec_backreferences():
    crunch64=pytest.importorskip('crunch64')
    for name in ('yaz0','mio0','yay0'):
        for raw in (b'abc'*1000,bytes(range(256))*10,b'x'*10000):
            decoded,codec=asset_formats.unpack(getattr(crunch64,name).compress(raw))
            assert decoded==raw and codec.lower()==name
