import base64
import struct

import pytest

from decompassets import formats
from decompassets.n64 import named_tim_archives

from .test_rom_assets import pixels


def tim():
    palette = struct.pack('<I4H16H',44,0,0,16,1,0,0x001f,0x03e0,0x7c00,*([0]*12))
    return struct.pack('<II',0x10,8)+palette+struct.pack('<I4H2B',14,0,0,1,1,0x21,0x03)


def archive():
    files = [(b'one.tim',tim()),(b'two.tim',tim()),(b'mesh.prm',b'abcd')]
    table = b''.join(name.ljust(16,b'\0')+struct.pack('<IIB',len(data),len(data),0) for name,data in files)
    return struct.pack('<H',len(files))+table+b''.join(data for _,data in files)


def test_named_archive_exposes_validated_tim_members():
    image = b'header'+archive()
    rows = named_tim_archives.regions(image)
    assert [r['label'] for r in rows] == ['one.tim','two.tim']
    result = named_tim_archives.preview(image,rows[0],{})
    rgba = pixels(base64.b64decode(result['data_url'].split(',')[1]))
    assert rgba[:8] == bytes([255,0,0,255,0,255,0,255])


def test_rejects_bad_member_extent_and_changed_texture():
    image = bytearray(archive())
    image[18:22] = (0xffffffff).to_bytes(4,'little')
    assert not named_tim_archives.regions(image)
    original = archive()
    asset, *_ = named_tim_archives.regions(original)
    with pytest.raises(formats.AssetError):
        named_tim_archives.preview(original[:-1],asset,{})


def test_needs_two_complete_named_textures():
    image = bytearray(archive())
    image[2+25+16:2+25+20] = (1).to_bytes(4,'little')
    assert not named_tim_archives.regions(image)
