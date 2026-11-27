import base64
import struct

import pytest

from decompassets import formats
from decompassets.n64 import named_cmp_textures

from .test_named_tim_archives import tim
from .test_rom_assets import pixels


def bits(values):
    text = ''.join(values)
    text += '0'*(-len(text)%8)
    return bytes(int(text[i:i+8],2) for i in range(0,len(text),8))


def literal(data):
    return bits(['1'+format(byte,'08b') for byte in data]+['0'+'0'*13])


def archive():
    image = tim()
    cmp = struct.pack('<3I',2,len(image),len(image))+literal(image+image)
    files = [(b'one.tim',image),(b'two.tim',image),(b'bank.cmp',cmp)]
    table = b''.join(name.ljust(16,b'\0')+struct.pack('<IIB',len(data),len(data),0) for name,data in files)
    return struct.pack('<H',len(files))+table+b''.join(data for _,data in files)


def test_named_compressed_bank_previews_each_complete_tim():
    image = archive()
    asset, = named_cmp_textures.regions(image)
    assert asset['frames'] == 2
    shown = named_cmp_textures.preview(image,asset,{'frame':1})
    rgba = pixels(base64.b64decode(shown['data_url'].split(',')[1]))
    assert rgba[:8] == bytes([255,0,0,255,0,255,0,255])


def test_ring_copy_can_overlap_and_requires_complete_end_marker():
    stream = bits(['1'+format(ord('A'),'08b'), '1'+format(ord('B'),'08b'),
                   '0'+format(1,'013b')+format(11,'04b'), '0'+'0'*13])
    assert named_cmp_textures.unpack(stream,16) == b'AB'*8
    with pytest.raises(formats.AssetError):
        named_cmp_textures.unpack(stream[:-1],16)
    with pytest.raises(formats.AssetError):
        named_cmp_textures.unpack(stream,15)


def test_bad_or_changed_compressed_bank_is_rejected():
    image = archive()
    asset, = named_cmp_textures.regions(image)
    assert not named_cmp_textures.regions(image[:-1])
    with pytest.raises(formats.AssetError):
        named_cmp_textures.preview(image[:-1],asset,{})


def test_directory_without_standalone_tim_needs_two_valid_banks():
    image = tim()
    compressed = struct.pack('<2I',1,len(image))+literal(image)
    files = [(b'one.cmp',compressed),(b'two.cmp',compressed)]
    table = b''.join(name.ljust(16,b'\0')+struct.pack('<IIB',len(data),len(data),0) for name,data in files)
    data = struct.pack('<H',len(files))+table+b''.join(payload for _,payload in files)
    rows = named_cmp_textures.regions(data)
    assert len(rows) == 2
    assert named_cmp_textures.preview(data,rows[-1],{})['details']['width'] == 4
    changed = bytearray(data)
    changed[-1] = 1
    assert not named_cmp_textures.regions(changed)
