"""Runtime task calls corroborate relocated local meshes in compressed data."""
import struct
import zlib

from decompassets import n64
from decompassets.n64 import runtime_deflate_models, runtime_packed_graphics


def fixture():
    data = bytearray(0x300)
    for i,point in enumerate(((0,0,0),(100,0,0),(0,100,0),(0,0,100))):
        struct.pack_into('>3hH2h4B',data,0x100+i*16,*point,0,i*7,i*11,20+i,40+i,60+i,255)
    commands = [(0x0400103f,0x100),(0xbe000000,6),(0xb1000204,0x00000406),
                (0xb1000602,0x00020604),(0xb8000000,0)]
    for i,command in enumerate(commands):
        struct.pack_into('>II',data,0x200+i*8,*command)
    compressor=zlib.compressobj(wbits=-15)
    stream=compressor.compress(data)+compressor.flush()
    image=bytes(0x100)+stream
    ram=bytearray(0x4000);ram[0x2000:0x2300]=data
    struct.pack_into('>I',ram,0x2204,0x2100)
    struct.pack_into('>4I',ram,0x800,0x06000000,0x80002200,0xb8000000,0)
    task=[1,0,0x80000100,0,0x80000100,0,0x80000100,0x800,0,0,0,0,0x80000800,16,0,0]
    struct.pack_into('>16I',ram,0x400,*task)
    return image,ram


def test_runtime_segment_zero_mesh_preview():
    image,ram=fixture()
    assets=runtime_packed_graphics.regions(image,[ram])
    asset=next(a for a in assets if a.get('layout')==runtime_deflate_models.LAYOUT)
    assert asset['offset']==0x100 and len(asset['meshes'])==1
    result=n64.preview(image,asset,{})
    assert result['media']=='model' and len(result['vertices'])==4 and result['triangles']==4
    assert 'animation' in result['note']


def test_model_requires_task_call_and_every_vertex_and_triangle_to_match():
    image,ram=fixture()
    for offset in (0x804, 0x2108, 0x2214):
        changed=bytearray(ram);changed[offset] ^= 1
        assert not any(a.get('layout')==runtime_deflate_models.LAYOUT
                       for a in runtime_packed_graphics.regions(image,[changed]))


def test_model_deduplicates_observations_and_rejects_truncated_stream():
    image,ram=fixture()
    assets=[a for a in runtime_packed_graphics.regions(image,[ram,ram])
            if a.get('layout')==runtime_deflate_models.LAYOUT]
    assert len(assets)==1 and len(assets[0]['meshes'])==1
    assert not any(a.get('layout')==runtime_deflate_models.LAYOUT
                   for a in runtime_packed_graphics.regions(image[:-1],[ram]))
