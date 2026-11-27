"""Packed textures whose RDP commands are assembled by CPU code."""

import base64
import struct
import zlib

from decompassets.n64 import constructed_resource_textures as textures


def _packed(data):
    chunks = [data[i:i+31] for i in range(0, len(data), 31)]
    payload = b''.join(bytes([0x80|len(chunk)])+chunk for chunk in chunks)
    return struct.pack('>I', len(payload)+4)+payload


def _fixture():
    image = bytearray(0x800)
    base, directory, destination = 0x800001f4, 0x200, 0x8024b000
    words = [0x000478c0, 0x3c190000|(base>>16), 0x27390000|(base&0xffff),
             0x25f8fff8, 0x03191821, 0x8c670010, 0x8c6a0014, 0x0520000e, 0x3c017fff]
    struct.pack_into('>9I', image, 0x40, *words)
    # The detector first filters code for these constructed RDP constants.
    image[0x80:0x90] = bytes.fromhex('3c01fd103c02fd503c03f5403c04f200')
    struct.pack_into('>2I', image, 0x180, 0x40000001, destination)
    image[0x140:0x160] = bytes.fromhex('f80107c1')+bytes(28)
    members = [_packed(bytes([0x01])*120)] + [_packed(b'other')]*7
    starts = [0x280]
    for member in members:
        starts.append(starts[-1]+((len(member)+1)&~1))
    for index, offset in enumerate(starts):
        struct.pack_into('>2I', image, directory+index*8, offset, offset|0x80000000)
    for start, member in zip(starts, members):
        image[start:start+len(member)] = member
    commands = [(0xfd100000,0x80000140), (0xe8000000,0), (0xf5000100,0x07000000),
                (0xe6000000,0), (0xf0000000,0x0703c000), (0xe7000000,0),
                (0xfd500000,destination), (0xf5500000,0x07040100), (0xe6000000,0),
                (0xf3000000,0x0703f000), (0xe7000000,0), (0xf5400200,0),
                (0xf2000000,(15<<14)|(15<<2))]
    events = []
    for index, (a,b) in enumerate(commands):
        for shift,value in [(0,a),(4,b)]:
            events.append(dict(kind='store', width=4, block=0, instruction=index*8+shift,
                               place=dict(kind='memory', value=index, offset=shift),
                               value=dict(kind='constant', value=value)))
    def read(*args, **kwargs):
        return {'events': events}
    context = dict(read_code=read, segments=[dict(vram=0x80000000,rom_start=0,rom_end=0x800)],
                   functions=[dict(vram=0x80000040,rom_offset=0x40,size=36),
                              dict(vram=0x80000080,rom_offset=0x80,size=24)])
    return image, context, events


def test_constructed_texture_uses_loader_palette_and_complete_rows():
    image, context, events = _fixture()
    asset, = textures.regions(image, context=context)
    assert (asset['width'], asset['height'], asset['tile_height']) == (16, 15, 16)
    result = textures.preview(image, asset, {})
    assert (result['details']['width'], result['details']['height']) == (16, 15)
    png = base64.b64decode(result['data_url'].split(',', 1)[1])
    length, = struct.unpack_from('>I', png, 33)
    assert zlib.decompress(png[41:41+length]) == (b'\0'+bytes.fromhex('ff0000ff 00ff00ff')*8)*15
    # A command in a different control-flow block cannot complete this sequence.
    events[-1]['block'] = 1
    assert textures.regions(image, context=context) == []


def test_constructed_texture_requires_unambiguous_code_and_resource():
    image, context, _ = _fixture()
    assert not textures.regions(image)
    image[0x284:0x286] = bytes(2)
    assert not textures.regions(image, context=context)
    image, context, _ = _fixture()
    context['segments'].append(dict(vram=0x80000000,rom_start=0x300,rom_end=0x500))
    assert not textures.regions(image, context=context)
    image, context, _ = _fixture()
    image[0x180] = 0x30
    assert not textures.regions(image, context=context)
