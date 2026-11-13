"""Invented bitstreams, glyphs and linked containers; no original assets."""
import struct

import pytest

from decompassets.formats import AssetError
from decompassets.n64 import animation, fonts, resources

from .test_native_resources import stream
from .test_native_textures import indexed_set


def packed(frames,signals,codes=None,initials=None):
    codes=codes or [0]*((frames+3)//4);initials=initials or [0]*len(signals)
    bits=[]
    def put(value,width):bits.extend((value>>i)&1 for i in range(width))
    for code in codes:put(code,6)
    for initial,signal in zip(initials,signals):
        put(initial,8)
        for value in signal:put(value&7,3)
    data=bytearray((len(bits)+7)//8)
    for i,bit in enumerate(bits):data[i//8]|=bit<<(i%8)
    return struct.pack('>H',frames)+data


def anim():
    frames=4;translation=struct.pack('>I4f',1,0,0,0,32767)+packed(frames,[[1]*frames,[0]*frames,[0]*frames])
    rotation=packed(frames,[[0]*frames]*4,initials=[0,0,0,127])
    return indexed_set([stream(2,frames),stream(4,1,struct.pack('>hh',0,0)),stream(20,1,struct.pack('>3f4h',0,0,0,0,0,0,32767)),
                        stream(len(translation),1,translation),stream(len(rotation),1,rotation),indexed_set([]),stream(20)])


def test_shared_headers_nonbyte_alignment_and_prediction():
    raw=packed(8,[[1,2,-1,0,1,1,1,1],[0]*8],codes=[0,16],initials=[0,128])
    assert animation.adpcm(raw,2,8)==[[1,3,2,2,3,4,5,6],[-32768]*8]
    assert animation.adpcm(packed(1,[[-4]],codes=[13],initials=[128]),1,1)==[[-32768]]
    for invalid in (raw[:-1],bytes(2),b''):
        with pytest.raises(AssetError):animation.adpcm(invalid,2,8)
    with pytest.raises(AssetError):animation.adpcm(raw,5,8)


def test_tracks_decode_translation_scale_and_rotation():
    result=animation.tracks(anim())
    assert result['frames']==4 and result['nodes'][0]['positions']==[[1,0,0],[2,0,0],[3,0,0],[4,0,0]]
    assert result['nodes'][0]['rotations'][0][3]==pytest.approx(32512/32767)
    raw=anim();parts=resources.blocks(raw,(0,len(raw)),7)
    missing=indexed_set([raw[a:b] if i not in (1,2) else stream(4,1,struct.pack('>hh',-1,-1)) if i==1 else stream(20) for i,(a,b) in enumerate(parts)])
    with pytest.raises(AssetError,match='initial'):animation.tracks(missing)


def glyph_image():
    base=0x80001000;pointer_at=16;glyph_at=128
    pointers=struct.pack('>26I',*(base+glyph_at+i*128 for i in range(26)))
    image=bytes(pointer_at)+pointers+bytes(glyph_at-pointer_at-len(pointers))+bytes(range(128))*26
    context=dict(segments=[dict(rom_start=0,rom_end=len(image),vram=base)],functions=[dict(name='Overlay__WriteText',relocs=[(0,5,base+pointer_at-4)])])
    return image,context


def test_native_font_requires_named_writer_unique_mapping_and_complete_glyphs():
    image,context=glyph_image();found=fonts.regions(image,context=context)
    assert len(found)==1 and found[0]['offset']==16 and found[0]['confidence']=='inferred'
    result=fonts.preview(image,found[0],{})
    assert result['font_atlas']['levels']==15 and result['table']['rows'][0]['character']=='A'
    assert result['font_atlas']['glyphs'][0]['pixels'][0]=='0001020304050607'
    assert not fonts.regions(image[:-1],context=context)
    context['functions'][0]['name']='unknown';assert not fonts.regions(image,context=context)
