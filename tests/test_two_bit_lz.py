import pytest

from decompassets.formats import AssetError
from decompassets.two_bit_lz import unpack


def test_literals_and_repeated_backreference():
    # Two literals, then a distance-two match of two bytes.
    data = b'\0\0\0\x04\x02AB\x01'
    assert unpack(data) == (b'ABAB', len(data))
    with pytest.raises(AssetError):
        unpack(data[:-1])
    with pytest.raises(AssetError):
        unpack(data[:-1] + b'\x1f')


def test_terminal_match_is_bounded_to_declared_output():
    data = b'\0\0\0\x03\x02AB\x01'
    assert unpack(data)[0] == b'ABA'
