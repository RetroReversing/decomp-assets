"""Homemade B1 graphs and predictor vectors; no commercial audio or source fixtures."""
import base64
import io
import struct
import wave

import pytest

from decompassets.formats import AssetError
from decompassets.n64 import audio

from .test_rom_assets import addiu, jal, lui, words


def fixture(*, raw=False, predictors=1):
    ctl=bytearray((320+8+32*predictors+15)//16*16)
    ctl[:8]=b'B1'+struct.pack('>HI',1,32)
    struct.pack_into('>HBBIII',ctl,32,1,0,0,22050,0,64)
    struct.pack_into('>BBBB',ctl,64,127,64,0,0)
    struct.pack_into('>HII',ctl,78,2,128,144)
    for sound,envelope,keymap,wavetable in [(128,192,224,256),(144,208,232,280)]:
        struct.pack_into('>IIIBBBx',ctl,sound,envelope,keymap,wavetable,64,127,0)
        struct.pack_into('>iiiBBxx',ctl,envelope,0,-1,16666,127,127)
        ctl[keymap:keymap+6]=bytes([0,127,0,127,60,0])
    length=32 if raw else 18
    for at,base in [(256,0),(280,40)]:struct.pack_into('>IIBBxxII',ctl,at,base,length,int(raw),0,0,0 if raw else 320)
    struct.pack_into('>II'+str(predictors*16)+'h',ctl,320,2,predictors,*([0]*(predictors*16)))
    # The table starts at the next 16-byte boundary after the predictor book.
    table=bytearray(72)
    for offset,value in [(0,1),(40,2)]:
        payload=struct.pack('>16h',*([value*1000,-value*1000]*8)) if raw else bytes([0])+bytes([value*17])*8
        if not raw:payload*=2
        table[offset:offset+len(payload)]=payload
    image=bytearray(128)+ctl+table
    base=128+len(ctl)
    code=words(lui(5,base),addiu(5,5,base),jal(0x80000040),0)
    image[:len(code)]=code
    functions=[dict(name='audio_loader',vram=0x80000000,rom_offset=0,size=len(code),relocs=[]),
               dict(name='alBnkfNew',vram=0x80000040,rom_offset=64,size=4,relocs=[])]
    return bytes(image),dict(functions=functions),base


def wav(result):
    with wave.open(io.BytesIO(base64.b64decode(result['data_url'].split(',')[1])),'rb') as stream:
        return stream.getframerate(),stream.readframes(stream.getnframes())


def test_adjacency_is_explicitly_tentative_and_raw_pcm_needs_a_named_base():
    image,_,_=fixture();found=audio.regions(image)
    assert found[0]['confidence']=='validated' and found[0]['table_confidence']=='tentative'
    assert all(row['confidence']=='tentative' for row in found[1:])
    image,_,_=fixture(raw=True);found=audio.regions(image)
    assert len(found)==1 and found[0]['audio_kind']=='unresolved bank'
    with pytest.raises(AssetError,match='unresolved'):audio.preview(image,found[0],{})


@pytest.mark.parametrize('offset,payload',[(128+4,b'\xff'*4),(128+34,b'\1'),(128+265,b'\1'),
    (128+320,struct.pack('>I',3)),(128+196,struct.pack('>i',-2)),(128+224,bytes([127,0]))])
def test_bad_pointers_flags_books_envelopes_and_key_maps_are_rejected(offset,payload):
    image,context,_=fixture();broken=bytearray(image);broken[offset:offset+len(payload)]=payload
    assert not audio.regions(broken,context=context)


def test_missing_predictors_and_truncated_sample_tables_never_classify_sample_bytes():
    image,context,base=fixture();broken=bytearray(image);broken[base]=1
    found=audio.regions(broken,context=context)
    assert len(found)==1 and found[0]['audio_kind']=='unresolved bank'
    assert len(audio.regions(image[:-32],context=context))==1
    with pytest.raises(AssetError,match='predictor'):audio.vadpcm(bytes([1])+bytes(8),[0]*16,1,16)


def test_adpcm_vectors_preserve_signed_nibbles_feedback_and_clipping():
    raw=bytes([0])+bytes.fromhex('718f000000000000')
    out=struct.unpack('<16h',audio.vadpcm(raw,[0]*16,1,16))
    assert list(out[:4])==[7,1,-8,-1]
    # A constant Q11 second-history coefficient gives a simple cumulative recurrence.
    book=[0]*8+[2048]*8
    assert struct.unpack('<16h',audio.vadpcm(bytes([0])+bytes([0x11])*8,book,1,16))==tuple(range(1,17))
    assert struct.unpack('<32h',audio.vadpcm((bytes([0])+bytes([0x11])*8)*2,book,1,32))==tuple(range(1,33))
    clipped=struct.unpack('<16h',audio.vadpcm(bytes([0xf0])+bytes([0x78])*8,[0]*16,1,16))
    assert clipped==(32767,-32768)*8
    changed=bytes([0x01])+bytes([0x11])*8
    assert struct.unpack('<16h',audio.vadpcm(changed,[2048]*16+[0]*16,2,16))==(1,)*16


def test_ambiguous_named_tables_are_not_chosen(monkeypatch):
    image,context,base=fixture();image+=bytes(8)+image[base:]
    second=len(image)-72
    monkeypatch.setattr(audio,'loader_tables',lambda *a,**k:{base:[],second:[]})
    found=audio.regions(image,context=context)
    assert len(found)==1 and found[0]['audio_kind']=='unresolved bank'


def test_header_budget_stop_and_false_magic_are_bounded(monkeypatch):
    image,context,_=fixture()
    monkeypatch.setattr(audio,'MAX_HEADER_CHECKS',1)
    assert len(audio.regions(image,context=context))==1
    def stop():raise RuntimeError('stop')
    with pytest.raises(RuntimeError,match='stop'):audio.regions(image,context=context,check=stop)
    monkeypatch.setattr(audio,'MAX_HEADER_CHECKS',100)
    prefix=b'B1random bytes'*200
    # Arbitrary B1 pairs do not consume the structural candidate budget.
    assert audio.regions(prefix+image)


def test_even_byte_padding_is_not_decoded_and_nonzero_padding_is_rejected():
    image,context,base=fixture();image=bytearray(image)
    struct.pack_into('>I',image,128+256+4,10)
    image[base:base+10]=bytes([0])+bytes([0x11])*8+bytes(1)
    found=audio.regions(image,context=context)
    _,pcm=wav(audio.preview(image,found[0],{}))
    assert struct.unpack('<16h',pcm)==(1,)*16
    image[base+9]=1
    assert audio.regions(image,context=context)[0]['audio_kind']=='unresolved bank'


def test_false_bank_headers_do_not_exhaust_the_graph_candidate_budget():
    image,_,_=fixture()
    found=audio.regions((b'B1\x00\x01'+bytes(4))*500+image)
    assert len(found)==3


def test_long_native_samples_preview_a_bounded_prefix_without_looping(monkeypatch):
    image,context,base=fixture();image=bytearray(image[:base])+bytearray(40000)
    raw=(bytes([0])+bytes([0x11])*8)*2757+bytes(1)
    image[base:base+len(raw)]=raw
    struct.pack_into('>I',image,128+256+4,len(raw))
    struct.pack_into('>I',image,128+280,32000)
    image[base+32000:base+32018]=(bytes([0])+bytes([0x22])*8)*2
    bank=audio.regions(image,context=context)[0]
    monkeypatch.setattr(audio,'MAX_SECONDS',1)
    result=audio.preview(image,bank,{})
    rate,pcm=wav(result)
    assert len(pcm)==rate*2 and result['details']['seconds']==1 and result['details']['truncated']
    assert result['details']['original_samples']>rate


@pytest.mark.parametrize('raw',[False,True])
def test_loop_endpoints_cannot_exceed_the_declared_sample_count(raw):
    image,_,_=fixture(raw=raw);image=bytearray(image)
    struct.pack_into('>I',image,128+256+12,368)
    struct.pack_into('>III',image,128+368,0,1000,1)
    with pytest.raises(audio.BankError,match='Loop'):audio.bank(image,128)

def test_wrapped_b1_finds_the_table_and_previews_each_sound():
    image,_,base=fixture()
    controls=bytearray(image[128:base])
    for field in (4,44,80,84,128,132,136,144,148,152,272,296):
        value=struct.unpack_from('>I',controls,field)[0]
        struct.pack_into('>I',controls,field,0x80000c+value)
    for flag in (34,67,142,158,265,289):
        controls[flag]=1
    prefix=bytes(128)+struct.pack('>III',1,0x80000c,0)
    wrapped=bytearray(prefix+controls+bytes(4)+image[base:])
    results=audio.regions(wrapped)
    bank=results[0]
    assert bank['offset']==128 and bank['table_offset']==base+16
    assert bank['table_confidence']=='tentative'
    assert [sample['label'] for sample in bank['samples']]==['Sample 1','Sample 2']
    for index in range(2):
        rate,pcm=wav(audio.preview(wrapped,bank,{'sample':index}))
        assert rate==22050 and struct.unpack('<32h',pcm)==(index+1,)*32

    bad_flag=bytearray(wrapped);bad_flag[len(prefix)+142]=0
    assert not audio.regions(bad_flag)
    wrapped[base+16]=15
    found=audio.regions(wrapped)
    assert len(found)==1 and found[0]['audio_kind']=='unresolved bank'
