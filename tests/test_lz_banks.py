"""Build a paired control stream and sequence directory without cartridge data."""

import struct

import pytest

from decompassets.formats import AssetError
from decompassets.n64 import lz_banks, preview

from .test_compact_midi import _sequence
from .test_native_audio import fixture, wav


def pack_bits(bits):
    bits += '0' * (-len(bits) % 8)
    return int(bits, 2).to_bytes(len(bits)//8, 'big')


def test_unpack_copies_overlapping_ring_tokens_and_checks_termination():
    literal = '1' + f'{ord("x"):08b}'
    match = '0' + f'{1:013b}' + '001'
    encoded = pack_bits(literal + match + '0'*14)
    assert lz_banks.unpack(b'abc' + encoded + b'other', 3) == (b'xxxxx', 3 + len(encoded))
    with pytest.raises(AssetError, match='Truncated'):
        lz_banks.unpack(encoded[:-1], 0)


def test_adjacent_controls_samples_and_sequence_preview():
    image, _, waves = fixture()
    control = image[128:waves]
    packed = pack_bits(''.join('1' + f'{byte:08b}' for byte in control) + '0'*14)
    table = image[waves:waves+58] + bytes(6)
    bank = packed + bytes(-len(packed) % 16) + table
    song = _sequence(bytes.fromhex('00 90 3c 60 81 00 00 ff 2f'))
    directory = struct.pack('>2sHII', b'S1', 1, 12, len(song)) + song + bytes(-len(song) % 4)
    image = bank * 2 + directory

    music, effects, songs = lz_banks.regions(image)
    assert music['table_offset'] == len(bank)-len(table)
    assert effects['offset'] == len(bank)
    assert songs['offset'] == 2*len(bank)
    assert wav(preview(image, effects, {'sample': 1}))[0] == 22050
    result = preview(image, songs, {'sample': 0})
    assert result['details']['mixed_notes'] == 1
    assert any(wav(result)[1])

    damaged = bytearray(image)
    damaged[music['table_offset']] = 1
    assert lz_banks.regions(damaged) == []
    assert lz_banks.regions(image[:songs['offset']]) == []
