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


# Arithmetic-coded literals produced from the homemade control graph.
_PACKED_CONTROL = bytes.fromhex(
        '000000f4c0437af8c1cfa2dfb61d888b4cf1859b3bc457ffe74b65f4074794a97b'
        '3fffffff89c5fc8de7f0bd2f9a177d6d17dde0bfffffffdb713fffd8385fc67ff'
        'fffffffffffffffffff8e3c9188ffff862dffcbd3e973ffffffffffffffffffff'
        'ffffffffffffffb757fb80b633fc0000')


@pytest.mark.parametrize('order', ['big','little'])
def test_lzari_controls_use_the_decoded_predictor_books(order):
    from decompassets.n64 import lzari

    packed = _PACKED_CONTROL if order == 'big' else _PACKED_CONTROL[:4][::-1]+_PACKED_CONTROL[4:]
    raw, consumed = lzari.unpack(packed,order=order)
    assert raw == fixture()[64:308] and consumed == len(packed)
    image = bytes(32)+packed+fixture()[320:]
    bank, first, second = ptr_audio.regions(image)
    assert bank['compressed_control'] == (32, len(packed))
    assert bank['control_byte_order'] == order
    assert bank['table_offset'] == 32+len(packed)
    for row, options in ((bank, {'sample':1}), (first, {}), (second, {})):
        assert any(wav(ptr_audio.preview(image,row,options))[2])
    with pytest.raises(lzari.LzariError, match='Truncated'):
        lzari.unpack(packed[:-5],order=order)
    with pytest.raises(lzari.LzariError, match='size'):
        lzari.unpack(packed,order=order,limit=len(raw)-1)


# Synthetic binary header, master tempo and two note tracks.
_PACKED_SONG = bytes.fromhex(
    '00000067fffffb9d19ffff7e7fff37afe53effa100fdb417e8cfbf9fa3d4d8feccb'
    '7ffffffffffffc09ce399bffffffffffe35dfe51a3462b5126d2778240d4de41cf9acf2a00000')


def test_binary_lzari_song_maps_instruments_and_renders_with_its_adjacent_bank():
    from decompassets import n64

    song = _PACKED_SONG
    image = bytes(32)+bytes.fromhex('00000001')+song+_PACKED_CONTROL+fixture()[320:]
    asset, = [row for row in n64.regions(image) if row.get('layout') == 'libmus-binary-song']
    assert asset['channels'] == 2 and asset['notes'] == 3
    assert asset['control'] == 36+len(song)
    rendered = n64.preview(image, asset, {'sample':0})
    assert rendered['details']['mixed_notes'] == 2
    assert any(wav(rendered)[2])
    detached = image[:asset['control']]+bytes(36)+image[asset['control']:]
    assert not any(row.get('layout') == 'libmus-binary-song' for row in n64.regions(detached))


def test_binary_effects_validate_the_track_directory_and_map_wave_ids():
    from decompassets.n64 import libmus_song

    track = bytes.fromhex('81 00 30 18 80')
    raw = struct.pack('>8I', 1,1,1,0,0,32+len(track),32,100)+track+struct.pack('>H',4)
    scores = libmus_song.binary_effects(raw,{4})
    assert [(note.wave,note.key,note.duration) for note in scores[0]['notes']] == [(4,48,24)]
    assert libmus_song.binary_effects(raw,{0}) is None
    assert libmus_song.binary_effects(raw[:-1],{4}) is None


def test_uncompressed_binary_song_follows_a_little_endian_bank_wave_table():
    from decompassets import n64
    from decompassets.n64 import lzari

    bank = _PACKED_CONTROL[:4][::-1]+_PACKED_CONTROL[4:]
    song, _ = lzari.unpack(_PACKED_SONG)
    image = bytes(32)+bank+fixture()[320:]
    image += bytes(-len(image)%8)+song
    asset, = [row for row in n64.regions(image) if row.get('layout') == 'libmus-binary-song']
    assert asset['control_byte_order'] == 'little' and not asset['sequence_packed']
    assert any(wav(n64.preview(image,asset,{'sample':0}))[2])


def test_binary_effect_count_is_independent_of_the_wave_lookup_count():
    from decompassets.n64 import libmus_song

    first = bytes.fromhex('81 00 30 18 80')
    second = bytes.fromhex('81 00 31 18 80')
    header = struct.pack('>10I',2,1,1,0,0,40+len(first)+len(second),40,100,40+len(first),100)
    raw = header+first+second+struct.pack('>H',4)
    assert [score['notes'][0].key for score in libmus_song.binary_effects(raw,{4})] == [48,49]
