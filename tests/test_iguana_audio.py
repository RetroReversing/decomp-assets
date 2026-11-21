import struct

from decompassets.n64 import audio, dean_codec, iguana_archive, iguana_audio, preview, regions

from .test_compact_midi import _sequence
from .test_dean_codec import _image
from .test_native_audio import fixture, wav
from .test_rnc import literal_block


def aligned(data):
    return data+bytes(-len(data)%4)


def archive(members):
    return b''.join(struct.pack('>I',len(data))+aligned(name+b'\0') for name,data in members)+bytes.fromhex(
        'ffffffff6d616b65')+b''.join(data for _,data in members)


def test_paired_music_and_relocated_waves_from_validated_iguana_directory():
    image,_,base=fixture()
    controls=bytearray(image[128:base])
    for field in (4,44,80,84,128,132,136,144,148,152,272,296):
        value, = struct.unpack_from('>I',controls,field)
        struct.pack_into('>I',controls,field,0x202000+value)
    for flag in (34,67,142,158,265,289):
        controls[flag]=1
    song=aligned(_sequence(bytes.fromhex('00 90 3c 60 18 00 ff 2f')))
    group=struct.pack('>III',1,12,len(song)+12)+song
    sound=struct.pack('>4I',2,16,20,20+len(group))+bytes(4)+group
    rom=archive([(b'CODE.BIN',aligned(literal_block(b'code'))),(b'data/sound/sfx.fsd',sound),
                 (b'data/sound/music.ctl',controls),(b'data/sound/music.tbl',image[base:])])
    directory,=iguana_archive.directories(rom)
    assert len(directory)==4
    bank,sequence=iguana_audio.regions(rom)
    assert bank['relocation']==0x202000 and len(bank['samples'])==2
    assert wav(audio.preview(rom,bank,{'sample':1}))[0]==22050
    result=preview(rom,sequence,{'sample':0})
    assert result['details']['channels']==2 and result['details']['mixed_notes']==1
    assert not iguana_audio.regions(rom[:-1])


def test_iguana_dean_directory_keeps_original_rate_and_requires_exact_extents():
    codebooks=_image(padding=16)
    payload=bytes(12)+b'\x80\0'+bytes(2)
    clip=aligned(struct.pack('>III',9450,2,len(payload))+payload)
    directory=struct.pack('>III',2,12,12+len(clip))+clip*2
    image=aligned(codebooks)+directory
    table=dean_codec.table_offset(image)
    assert table==0
    start=len(aligned(codebooks))
    first,second=iguana_audio._dean_rows(image,start,len(image),table,lambda:None)
    for item in (first,second):
        rate, samples=wav(preview(image,item,{}))
        assert rate==9450 and len(samples)==256 and any(samples)
    assert not iguana_audio._dean_rows(image,start,len(image)-1,table,lambda:None)
    rom=archive([(b'CODE.BIN',aligned(literal_block(b'code'))),(b'data/sound/pbpsfx.bin',directory),
                 (b'extra.bin',b'data'),(b'books.bin',aligned(codebooks))])
    reported=[asset for asset in regions(rom) if asset.get('layout')=='iguana-dean']
    assert len(reported)==2 and all(asset['table_offset'] for asset in reported)
