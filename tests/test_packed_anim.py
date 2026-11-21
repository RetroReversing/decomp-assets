import base64
import struct

from decompassets import n64
from decompassets.n64 import packed_anim


def _image(*, tail=b'', encoded=b'\x01\x11\xee\xf0'):
    header = b'ANIM'+struct.pack('>3I',1,1,30)+bytes(32)
    palette = bytes(3)+bytes([248,0,0])+bytes(42)
    frame = palette+encoded+tail
    return header+struct.pack('>I4HBB2s',16+len(frame),4,2,0,0,4,1,b'LZ')+frame


def test_packed_anim_uses_overlap_and_ignores_alignment_bytes():
    image = _image(tail=b'\x23\x99')
    asset, = packed_anim.regions(image)
    frame = packed_anim._frame(image,asset['offset'],lambda: None)
    assert frame[-1] == bytes([0x11])*4
    result = n64.preview(image,asset,{})
    png = base64.b64decode(result['data_url'].split(',')[1])
    assert struct.unpack_from('>2I',png,16) == (4,2)


def test_packed_anim_rejects_truncation_and_unwritten_ring():
    assert not packed_anim.regions(_image(encoded=b'\x01'))
    assert not packed_anim.regions(_image(encoded=b'\x00\xee\xf1'))
    assert not packed_anim.regions(_image()[:-1])
