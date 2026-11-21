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


def test_uv_form_pairs_named_control_and_wave_chunks():
    def chunk(tag, body):
        return tag+struct.pack('>I', len(body))+body

    image, _, base = fixture(raw=True)
    control, table = image[128:base], image[base:]
    form = chunk(b'FORM', b'UVSX'+chunk(b'.CTL', control)+chunk(b'.TBL', table))
    bank = audio.regions(form)[0]
    assert bank['table_confidence'] == 'validated'
    assert len(bank['samples']) == 2
    assert len(wav(audio.preview(form, bank, {}))[1]) == 32
    # Valid trailing ROM bytes cannot compensate for a truncated wave chunk.
    short = chunk(b'FORM', b'UVSX'+chunk(b'.CTL', control)+chunk(b'.TBL', table[:-1]))+table[-1:]
    assert not audio.regions(short)


def test_bank_preserves_keymaps_when_programs_share_a_wavetable():
    image, _, _ = fixture()
    image = bytearray(image)
    struct.pack_into('>H', image, 128+32, 2)
    struct.pack_into('>I', image, 128+48, 64)
    struct.pack_into('>I', image, 128+144+8, 256)
    image[128+232:128+238] = bytes([10, 100, 70, 90, 74, 253])
    bank = audio.bank(image, 128)
    assert len(bank['samples']) == 1
    first, second = bank['programs'][0, 1]
    assert first['sample'] is second['sample']
    assert second['velocity_range'] == (10, 100)
    assert second['key_range'] == (70, 90)
    assert second['key_base'] == 74 and second['detune'] == -3
    assert bank['programs'][0, 0] is bank['programs'][0, 1]


def test_sample_bank_with_unset_midi_keys_requires_valid_adjacent_frames():
    image, _, base = fixture()
    broken = bytearray(image)
    broken[128+224] = broken[128+232] = 255
    with pytest.raises(audio.KeyMapError):
        audio.bank(broken, 128)
    found = audio.regions(broken)
    assert len(found[0]['samples']) == 2
    assert wav(audio.preview(broken, found[0], {}))[0] == 22050
    broken[base] = 15
    assert not audio.regions(broken)


@pytest.mark.parametrize('same_buffer',[True,False])
def test_unnamed_b1_relocator_pairs_the_copied_control_with_its_sample_table(same_buffer):
    original,_,base = fixture(raw=True)
    control, wave_at = 128, 1024
    image = bytearray(original[:base] + bytes(wave_at-base) + original[base:])
    copy_pc, link_pc = 0x80000300, 0x80000380
    image[:4] = words(jal(link_pc))
    image[512:536] = words(0x00809021,0x00a08821,0x00c08021,0xafb00014,0x02403821,0xafb10010)
    image[640:660] = words(0x848e0000,0x24014231,0x00808025,0x15c1002e,0x848f0002)
    functions = [dict(name='caller',vram=0x80000000,rom_offset=0,size=48),
                 dict(name='copy',vram=copy_pc,rom_offset=512,size=0x70),
                 dict(name='link',vram=link_pc,rom_offset=640,size=0x70)]
    def constant(value):
        return dict(kind='constant',value=value,offset=0)

    def read(vram, code, **kwargs):
        pointer = constant(0x80200000)
        location = constant(0x80100000)
        written = location if same_buffer else constant(0x80100010)
        return dict(events=[
            dict(kind='call', target=copy_pc, instruction=vram, block=0,
                 args=[constant(0xb0000000+control),pointer,constant(base-control)],
                 memory=[dict(place=written,value=pointer)]),
            dict(kind='load', width=4, instruction=vram+8, place=location),
            dict(kind='call', target=link_pc, instruction=vram+16, block=0,
                 args=[dict(kind='memory',value=vram+8),constant(0xb0000000+wave_at)]),
        ])

    banks = audio.regions(bytes(image), context=dict(functions=functions,read_code=read))
    bank = banks[0]
    if same_buffer:
        assert bank['table_offset']==wave_at and bank['table_confidence']=='validated'
        assert len(bank['samples'])==2 and wav(audio.preview(bytes(image),bank,{}))[0]==22050
    else:
        assert bank['audio_kind']=='unresolved bank'


@pytest.mark.parametrize('matching_buffer', [True, False])
def test_pi_wrapper_forwards_b1_control_and_wave_table(matching_buffer):
    original, _, base = fixture(raw=True)
    control, wave_at = 128, 1024
    image = bytearray(original[:base] + bytes(wave_at-base) + original[base:])
    caller_pc, wrapper_pc, dma_pc, link_pc = 0x80000000, 0x80000200, 0x80000300, 0x80000380
    image[:4] = words(jal(wrapper_pc))
    image[512:516] = words(jal(link_pc))
    image[640:664] = words(0x8fa40028, 0x8fa8002c, 0xa6020000, 0xae07000c, 0xae040008, 0xae080010)
    image[768:788] = words(0x00809021, 0x864e0000, 0x24014231, 0x15c1002e, 0x864f0002)
    functions = [dict(name=name, vram=pc, rom_offset=offset, size=0x70)
                 for name, pc, offset in [('caller', caller_pc, 0), ('wrapper', wrapper_pc, 512),
                                          ('dma', dma_pc, 640), ('link', link_pc, 768)]]

    def constant(value):
        return dict(kind='constant', value=value, offset=0)

    def argument(index):
        return dict(kind='argument', value=index, offset=0)

    def read(vram, code, **kwargs):
        if vram == caller_pc:
            return dict(events=[dict(kind='call', target=wrapper_pc, instruction=vram, block=0,
                                     args=[constant(0xb0000000+control), constant(base-control),
                                           None, constant(0xb0000000+wave_at)])])
        pointer = constant(0x80200000)
        location = constant(0x80100000)
        written = location if matching_buffer else constant(0x80100010)
        return dict(events=[
            dict(kind='store', width=4, instruction=vram, block=0, place=written, value=pointer),
            dict(kind='call', target=dma_pc, instruction=vram+4, block=0,
                 args=[None, None, None, argument(0), pointer, argument(1)]),
            dict(kind='call', target=0x80001000, instruction=vram+8, block=0, args=[]),
            dict(kind='load', width=4, instruction=vram+16, place=location),
            dict(kind='call', target=link_pc, instruction=vram+24, block=0,
                 args=[dict(kind='memory', value=vram+16, offset=0), argument(3)]),
        ])

    bank = audio.regions(bytes(image), context=dict(functions=functions, read_code=read))[0]
    if matching_buffer:
        assert bank['table_offset'] == wave_at
        assert bank['table_confidence'] == 'validated'
        assert wav(audio.preview(bytes(image), bank, {}))[0] == 22050
    else:
        assert bank['audio_kind'] == 'unresolved bank'


def test_sparse_effects_bank_accepts_more_than_256_instrument_slots():
    image, _, wave_start = fixture()
    control = bytearray(image[128:wave_start])
    header = len(control)
    slots = 398
    control[:8] = b'B1' + struct.pack('>HI', 1, header)
    control.extend(struct.pack('>HBBII', slots, 0, 0, 22050, 0))
    control.extend(bytes(4 * (slots - 1)) + struct.pack('>I', 64))
    bank = audio.bank(control, 0)
    assert len(bank['samples']) == 2
    assert (0, slots - 1) in bank['programs']
    assert (0, 0) not in bank['programs']
    struct.pack_into('>H', control, header, audio.MAX_INSTRUMENTS + 1)
    with pytest.raises(audio.BankError, match='bank header'):
        audio.bank(control, 0)


def test_unnamed_guarded_b1_loader_resolves_kseg1_sample_table():
    data, context, base = fixture(raw=True)
    image = bytearray(data[:64] + bytes(128) + data[128:])
    # The synthetic relocator validates the B1 magic and reads the bank count.
    body = words(0x84820000, 0x24034231, 0x14430002, 0, 0x84820002) + bytes(0x70 - 20)
    image[64:64+len(body)] = body
    context['functions'][1].update(name='func_80000040', size=len(body))
    rom_base = base + 64
    struct.pack_into('>IIBBxxII', image, 192+256, 0, 18, 0, 0, 0, 320)
    image[rom_base:rom_base+18] = (bytes([0]) + bytes([0x11])*8)*2
    call = words(lui(5, 0xb000), addiu(5, 5, rom_base), jal(0x80000040), 0)
    image[:len(call)] = call

    def read(*args, **kwargs):
        return {'events': [dict(kind='call', target=0x80000040, instruction=8,
                                args=[None, dict(kind='constant', value=0xb0000000 + rom_base)])]}

    context['read_code'] = read
    bank = audio.regions(image, context=context)[0]
    assert bank['table_offset'] == rom_base
    assert wav(audio.preview(image, bank, {'sample': 1}))[1]
    image[64:68] = bytes(4)
    assert audio.regions(image, context=context)[0]['audio_kind'] == 'unresolved bank'


def test_parallel_control_and_wave_tables_resolve_nonadjacent_banks():
    single, _, base = fixture(raw=True)
    control, waves = single[128:base], single[base:]
    first = 128
    second = first + len(control)
    wave_start = second + len(control)
    second_wave = wave_start + ((len(waves) + 15) & ~15)
    directory = struct.pack('>6I', first, second, second, wave_start, wave_start, second_wave)
    image = directory.ljust(first, b'\0') + control * 2 + waves.ljust(second_wave - wave_start, b'\0') + waves

    banks = [asset for asset in audio.regions(image) if len(asset['samples']) == 2]
    assert [(bank['offset'], bank['table_offset'], bank['table_confidence']) for bank in banks] == [
        (first, wave_start, 'validated'), (second, second_wave, 'validated'),
    ]
    assert any(wav(audio.preview(image, banks[0], {'sample': 1}))[1])

    broken = bytearray(image)
    broken[11] ^= 1
    assert all(asset['audio_kind'] == 'unresolved bank' for asset in audio.regions(broken))
    broken = bytearray(image)
    struct.pack_into('>I', broken, 20, wave_start + 48)
    assert not any(asset['offset'] == first and asset['samples'] for asset in audio.regions(broken))
