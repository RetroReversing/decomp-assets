"""RefPack validates all command forms, output bounds and stream termination."""

import pytest

from decompassets.formats import AssetError
from decompassets.refpack import unpack


def test_literal_and_three_backreference_forms():
    stream = b'\x10\xfb\x00\x00\x10\xe0ABCD\x00\x03\x80\x00\x06\xc0\x00\x00\x00\xfc'
    assert unpack(stream) == (b'ABCDABCABCDDDDDD', len(stream))
    from decompassets.formats import unpack_extent
    assert unpack_extent(stream) == (b'ABCDABCABCDDDDDD', 'RefPack', len(stream))
    with pytest.raises(AssetError):
        unpack(stream[:-1])
    with pytest.raises(AssetError):
        unpack(stream[:4] + b'\x0f' + stream[5:])
    with pytest.raises(AssetError):
        unpack(b'\x10\xfb\x00\x00\x03\x00\x00\xfc')
