"""Synthetic BOLT members covering exact decode, catalog bounds and preview dispatch."""

import struct

from decompassets import n64
from decompassets.n64 import bolt, bolt_audio


def archive(records):
    header = b'BOLT'+bytes((1,2,3,0,4,5,100,1))+bytes(4)
    stored = sum(len(data) for _,data in records)
    root = bolt.ENTRY.pack(8,0,0,len(records),stored,32,0)
    leaves = []
    at = 32+16*len(records)
    for index,(kind,data) in enumerate(records,1):
        leaves.append(bolt.ENTRY.pack(8,0,0,kind,len(data),at,index))
        at += len(data)
    return header+root+b''.join(leaves)+b''.join(data for _,data in records)


def model():
    image = bytearray(136)
    struct.pack_into('>I',image,4,len(image))
    struct.pack_into('>4I',image,24,64,3,112,3)
    for i,(x,y) in enumerate(((0,0),(1,0),(0,1))):
        struct.pack_into('>hh',image,64+16*i,x,y)
    struct.pack_into('>6I',image,112,0x01003006,64,0x05000204,0,0xdf000000,0)
    return image


def test_bolt_lzss_checks_exact_output_and_overlapping_copies():
    data = b'\x81AB\x11'
    assert bolt.inflate(data,5) == (b'ABABA',4)
    assert bolt.inflate(data,4) is None
    assert bolt.inflate(data[:-1],5) is None
    assert bolt.inflate(b'\x00',2) is None


def test_bolt_dispatches_bounded_texture_geometry_and_voice():
    voice = struct.pack('>HHII',0x0210,16384,2,0)+b'\x18\x00'
    image = archive([(8,bytes(2048)),(26,model()),(25,voice)])
    texture, mesh, audio = bolt.regions(image)
    assert n64.preview(image,texture,{})['details']['width'] == 32
    assert n64.preview(image,mesh,{})['triangles'] == 1
    assert n64.preview(image,audio,{})['mime'] == 'audio/wav'
    assert not bolt.regions(image[:-1])
    assert struct.unpack('<4h',bolt_audio.pcm(voice[12:],2)) == (96,64,96,128)
