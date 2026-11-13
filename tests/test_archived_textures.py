"""Embedded archives and pointer-rebuilt texture records use only homemade bytes."""
import base64
import io
import struct
import zipfile

import pytest

from decompassets import archives as asset_archives
from decompassets import formats as asset_formats
from decompassets.n64 import texture_packs

from .test_rom_assets import pixels


def pack(records=((16,8,4,1,1),)):
    data=bytearray(bytes([len(records),2])+bytes(6+len(records)*4))
    for fmt,width,height,palettes,frames in records:
        data.extend(bytes(-len(data)%8));head=bytearray(32)
        struct.pack_into('>HHHBB',head,4,fmt,width,height,palettes,frames)
        data.extend(head);data.extend(bytes(4*(palettes+frames)))
        if fmt!=160:
            for index in range(palettes):
                color=b'\xf8\x01' if index==0 else b'\x00\x3f'
                data.extend(color*fmt)
        for frame in range(frames):
            if frames>1 or palettes>1:data.extend(bytes(-len(data)%8))
            if fmt==16:data.extend(bytes([frame%16*17])*(width*height//2))
            elif fmt==256:data.extend(bytes([frame])*width*height)
            else:data.extend(bytes([240,16,32,255])*(width*height))
    data.append(len(records));return bytes(data)


def archive(data=None,method=zipfile.ZIP_DEFLATED,*,name='textures/demo.pack'):
    out=io.BytesIO()
    with zipfile.ZipFile(out,'w',compression=method) as z:
        z.writestr(name,data if data is not None else pack())
        z.writestr('other/notes.txt','A synthetic non-texture member')
    return bytes(64)+out.getvalue()+bytes(100000)


@pytest.mark.parametrize('method',[zipfile.ZIP_STORED,zipfile.ZIP_DEFLATED])
def test_embedded_zip_offsets_padding_crc_and_no_extraction(method,tmp_path):
    image=archive(method=method,name='../display-only.pack')
    members=asset_archives.zip_members(image)
    assert len(members)==2 and members[0]['name']=='../display-only.pack'
    assert asset_archives.member_bytes(image,members[0])==pack()
    assert asset_archives.member_bytes(image,members[0],prefix=True)==pack()[:32]
    assert members[0]['offset']==64 and not list(tmp_path.iterdir())
    corrupted=bytearray(image);corrupted[members[0]['payload']+members[0]['packed']//2]^=1
    with pytest.raises(asset_formats.AssetError):asset_archives.member_bytes(corrupted,members[0])
    # A forged expansion length cannot turn the bounded inflater into a bomb.
    with pytest.raises(asset_formats.AssetError):asset_archives.member_bytes(image,{**members[0],'expanded':1})
    with pytest.raises(asset_formats.AssetError):asset_archives.member_bytes(image,{**members[0],'expanded':asset_archives.MAX_MEMBER+1})


def test_zip_central_local_consistency_truncation_and_cancellation():
    image=bytearray(archive());local=image.find(b'PK\x03\x04');central=image.find(b'PK\x01\x02')
    assert not asset_archives.zip_members(image[:central+10])
    image[local+8]=99
    assert not asset_archives.zip_members(image)
    image=bytearray(archive());image[central+42:central+46]=b'\xff'*4
    assert not asset_archives.zip_members(image)
    def stop():raise RuntimeError('Stopped')
    with pytest.raises(RuntimeError,match='Stopped'):texture_packs.regions(archive(),check=stop)


def test_palette_and_frame_choices_are_checked_against_selected_texture():
    image=archive(pack(((16,8,4,2,1),(16,4,4,1,2))))
    asset=texture_packs.regions(image)[0]
    first=texture_packs.preview(image,asset,dict(texture=0,palette=0))
    second=texture_packs.preview(image,asset,dict(texture=0,palette=1))
    assert first['data_url']!=second['data_url']
    assert pixels(base64.b64decode(first['data_url'].split(',')[1]))[:4]==b'\xff\0\0\xff'
    assert pixels(base64.b64decode(second['data_url'].split(',')[1]))[:4]==b'\0\0\xff\xff'
    assert texture_packs.preview(image,asset,dict(texture=1,frame=1))['settings']['frame']==1
    with pytest.raises(asset_formats.AssetError):texture_packs.preview(image,asset,dict(texture=0,frame=1))
    with pytest.raises(asset_formats.AssetError):texture_packs.preview(image,asset,dict(texture=1,palette=1))


def test_invalid_or_partial_packs_never_become_detected_textures():
    original=pack()
    for data in (original[:-2]+original[-1:],original+b'\0',bytes(64),pack(((16,8,4,2,2),)),pack(((16,3,4,1,1),))):
        assert texture_packs.layout(data) is None
        assert texture_packs.regions(archive(data))==[]
    image=archive(original);member=asset_archives.zip_members(image)[0]
    assert texture_packs.regions(image[:member['payload']+member['packed']])==[]


def test_archive_scan_honours_expansion_budget(monkeypatch):
    monkeypatch.setattr(texture_packs,'MAX_EXPANDED',len(pack())-1)
    assert texture_packs.regions(archive())==[]


def test_zip_data_descriptors_and_duplicate_end_records_are_bounded():
    class Streaming(io.BytesIO):
        def seek(self,*args):raise OSError('Streaming writer')
    out=Streaming()
    with zipfile.ZipFile(out,'w',compression=zipfile.ZIP_DEFLATED) as z:z.writestr('stream.pack',pack())
    image=bytes(32)+out.getvalue()+bytes(20)
    members=asset_archives.zip_members(image)
    assert len(members)==1 and asset_archives.member_bytes(image,members[0])==pack()
    assert len(texture_packs.regions(image))==1
