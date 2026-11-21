"""Pointer bank fixtures contain homemade predictor books and waveform frames."""
import base64
import io
import struct
import wave

import pytest

from decompassets.formats import AssetError
from decompassets.n64 import ptr_audio


def fixture(*,frames=2,pcm=False,loop=False):
    control=bytearray(256);control[:16]=ptr_audio.MAGIC;control[20:32]=b'synthetic\0\0\0'
    struct.pack_into('>4I',control,32,2,232,236,224)
    struct.pack_into('>2I',control,224,48,112);control[232:234]=bytes([48,244])
    raw=(b'\0\1\xff\xfe'*4) if pcm else bytes([0,0x12,0x34,0x56,0x78,0x9a,0xbc,0xde,0xf0])*frames
    second=(16+len(raw)+15)//16*16
    for at,base,book in [(48,16,72),(112,second,136)]:
        struct.pack_into('>II',control,at,base,len(raw));control[at+8]=1 if pcm else 0
        struct.pack_into('>II',control,at+12,176 if loop else 0,0 if pcm else book)
        if not pcm:struct.pack_into('>II',control,book,2,1)
    if loop:struct.pack_into('>III',control,176,0,8 if pcm else frames*16,0xffffffff)
    table=ptr_audio.WAVES+raw+bytes(second-16-len(raw))+raw
    return bytes(64)+control+table


def wav(result):
    with wave.open(io.BytesIO(base64.b64decode(result['data_url'].split(',')[1])),'rb') as stream:return stream.getframerate(),stream.getnframes(),stream.readframes(stream.getnframes())


def test_ambiguous_missing_and_invalid_wave_tables_remain_unplayable():
    image=fixture();table=image[320:]
    for data in [image[:320],image+bytes(16)+table,image[:336]+b'\x0f'+image[337:]]:
        assets=ptr_audio.regions(data)
        assert len(assets)==1 and assets[0]['samples']==[] and assets[0]['table_confidence']=='unresolved'
        with pytest.raises(AssetError,match='no uniquely fitting'):ptr_audio.preview(data,assets[0],{})


@pytest.mark.parametrize('offset,value',[(16,0x80000000),(32,999999),(36,0xfffffffc),(44,0xfffffffc),(72,3),(76,9),(48+16,0xfffffffc)])
def test_invalid_relocated_graphs_and_books_are_rejected(offset,value):
    data=bytearray(fixture());struct.pack_into('>I',data,64+offset,value)
    assert ptr_audio.regions(data)==[]


def test_bad_flags_loops_tuning_and_sample_bounds_are_not_classified():
    for offset,value in [(64+48+9,1),(64+236+1,1)]:
        data=bytearray(fixture());data[offset]=value;assert ptr_audio.regions(data)==[]
    data=bytearray(fixture(loop=True));struct.pack_into('>I',data,64+176+4,99999)
    assert ptr_audio.regions(data)==[]
    data=bytearray(fixture());struct.pack_into('>I',data,64+48,0xfffffff0)
    assets=ptr_audio.regions(data);assert len(assets)==1 and not assets[0]['samples']


def test_budget_cancellation_and_preview_limits(monkeypatch):
    def stop():raise RuntimeError('Stopped')
    with pytest.raises(RuntimeError,match='Stopped'):ptr_audio.regions(fixture(),check=stop)
    monkeypatch.setattr(ptr_audio,'MAX_FRAME_CHECKS',1)
    assert not ptr_audio.regions(fixture())[0]['samples']
    monkeypatch.setattr(ptr_audio,'MAX_FRAME_CHECKS',100000)
    image=fixture(frames=2000);asset=ptr_audio.regions(image)[0]
    result=ptr_audio.preview(image,asset,{'rate':1000})
    assert result['details']['truncated'] and wav(result)[1]==30000
    for options in [{'sample':2},{'rate':999},{'rate':192001}]:
        with pytest.raises(AssetError):ptr_audio.preview(image,asset,options)


def test_raw_song_preview_mixes_wave_bank_and_validates_table():
    from decompassets.n64 import libmus_song

    bank = fixture(pcm=True, loop=True)
    bank += bytes((-len(bank))%4)
    first = bytes.fromhex('81 01 85 78 8d f4 86 00 0c 48 18 80')
    second = bytes.fromhex('81 01 9c fe a6 00 40 18 80')
    tracks = struct.pack('>12I', 2,24,32,40,48,48,48,48+len(first),0,0,0,0)
    image = bank+tracks+first+second
    asset, = libmus_song.regions(image, ptr_audio.regions(image))
    assert libmus_song.preview(image, asset, {})['fields']['Notes'] == 2
    result = libmus_song.preview(image, asset, dict(sample=0))
    assert result['details']['channels'] == 2
    assert result['details']['mixed_notes'] == 1
    assert any(wav(result)[2])
    broken = image[:asset['table_offset']]+b'X'+image[asset['table_offset']+1:]
    with pytest.raises(AssetError, match='failed sample validation'):
        libmus_song.preview(broken, asset, dict(sample=0))
