
from decompassets.n64 import relative_audio

from .test_native_audio import fixture


def literals(data):
    bits = ''.join('1' + format(value, '08b') for value in data) + '0' * 14
    bits += '0' * (-len(bits) % 8)
    return int(bits, 2).to_bytes(len(bits) // 8, 'big')


def test_bounded_control_stream_and_sample_bank():
    source, _, table = fixture()
    control = source[128:table]
    packed = literals(control)
    image = bytearray(16) + packed
    image.extend(bytes((-len(image)) % 16))
    sample_table = len(image)
    image.extend(source[table:])
    assert relative_audio.unpack(image, 16, len(image))[0] == control
    _, bank, found_table, _ = relative_audio._bank(image, 16, lambda: None)
    assert found_table == sample_table
    assert len(bank['samples']) == 2
    image[sample_table] = 1
    assert relative_audio._bank(image, 16, lambda: None) is None
    assert relative_audio.unpack(b'\xff', 0, 1) is None


def test_backreference_reads_the_sliding_window():
    # Two literals, then four bytes from the initialized window, then the end marker.
    encoded = '1' + format(ord('B'), '08b') + '1' + format(ord('1'), '08b')
    encoded += '0' + format(1, '013b') + format(1, '03b') + '0' * 14
    encoded += '0' * (-len(encoded) % 8)
    raw = int(encoded, 2).to_bytes(len(encoded) // 8, 'big')
    assert relative_audio.unpack(raw, 0, len(raw))[0] == b'B1B1B1'


def test_compressed_song_uses_its_instrument_samples():
    import gzip
    import struct

    source, _, table = fixture()
    image = bytearray(16) + literals(source[128:table])
    image.extend(bytes((-len(image)) % 16))
    sample_table = len(image)
    image.extend(source[table:])
    score = bytearray(68)
    struct.pack_into('>I', score, 0, 68)
    struct.pack_into('>I', score, 64, 480)
    score.extend(bytes.fromhex('00 90 3c 64 08 08 ff 2f'))
    start = len(image)
    image.extend(gzip.compress(score, mtime=0))
    asset = dict(layout=relative_audio.SONG, offset=start, size=len(image)-start,
                 control=16, table_offset=sample_table, preview_settings=dict(source='rom', format='auto', offset=start))
    result = relative_audio.preview(image, asset, {})
    assert result['media'] == 'audio'
    assert result['details']['mixed_notes'] == 1
    assert result['details']['skipped_notes'] == 0
