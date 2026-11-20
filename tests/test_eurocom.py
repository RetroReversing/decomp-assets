import struct

import pytest

from decompassets import n64
from decompassets.formats import AssetError
from decompassets.n64 import edl, eurocom, eurocom_mesh


def _stored(data):
    return struct.pack('>4sII', b'EDL\x80', 12 + len(data), len(data)) + data


def _bitstream(method, size, *fields):
    value = offset = 0
    for item, width in fields:
        value |= item << offset
        offset += width
    words = b''.join(struct.pack('>I', (value >> shift) & 0xffffffff) for shift in range(0, offset, 32))
    return struct.pack('>4sII', b'EDL' + bytes([128 + method]), 12 + len(words), size) + words


def test_edl_fixed_match_and_huffman_stored_run():
    fixed = _bitstream(2, 5, (0, 1), (65, 8), (1, 1), (0, 1), (0, 1), (0, 1), (0, 1), (0, 8), (15, 4), (0, 8))
    assert edl.unpack(fixed) == b'AAAAA'
    assert edl.unpack(_bitstream(1, 2, (0, 1), (2, 15), (66, 8), (67, 8), (1, 1))) == b'BC'
    with pytest.raises(AssetError):
        edl.unpack(fixed[:-4])
    invalid = bytearray(fixed)
    struct.pack_into('>I', invalid, 8, 4)
    with pytest.raises(AssetError, match='bounds'):
        edl.unpack(bytes(invalid))


def test_eurocom_index_and_palette_preview_use_relative_offsets():
    count = 8
    base = (count + 1) * eurocom.INDEX.size
    image = bytearray(base)
    for index in range(count):
        pixel_offset = len(image) - base
        tex = _stored(b'\x01\x10\x00\x11')
        image.extend(tex)
        palette_offset = len(image) - base
        palette = _stored(b'\xff\xff\xf8\x01' + b'\0\0'*14)
        image.extend(palette)
        ptable = len(image) - base
        image.extend(eurocom.PAL.pack(15, 0))
        ttable = len(image) - base
        image.extend(eurocom.TEX.pack(0, 3, 1, 0))
        header = len(image) - base
        image.extend(eurocom.ENTRY.pack(0, 0, 0, 0, ptable, 1, ttable, 1,
                                        palette_offset, len(palette), pixel_offset, len(tex)))
        eurocom.INDEX.pack_into(image, index*eurocom.INDEX.size, header, 0, 0, 1)

    assets = n64.regions(bytes(image))
    index, = [asset for asset in assets if asset.get('layout') == 'eurocom-index']
    textures = [asset for asset in assets if asset.get('layout') == 'eurocom-textures']
    assert len(textures) == index['texture_total'] == count
    assert n64.preview(bytes(image), index, {})['table']['total'] == count
    result = n64.preview(bytes(image), textures[0], {})
    assert result['data_url'].startswith('data:image/png;base64,')
    assert result['details']['width'] == 4


def test_eurocom_mesh_rejects_bad_cached_vertex_reference():
    vertices = struct.pack('>9f', 0, 0, 0, 1, 0, 0, 0, 1, 0)
    commands = bytes((0, 3, 0, 0, 0, 1, 0, 0, 2, 0, 0, 5, 1, 0, 1, 2, 12))
    header = eurocom_mesh.DESCRIPTOR.pack(32, 3, 0, 0, 1, 0, 0, 1, 0, 68, len(commands), 0)
    image = header + vertices + commands
    assert eurocom_mesh.mesh(image, 0, 0) == (32, 3, [[0, 1, 2]])
    assert eurocom_mesh.mesh(image[:-2] + bytes((32, 12)), 0, 0) is None


def test_musyx_sample_preview_uses_predictor_book_and_both_frame_seeds():
    import base64
    import io
    import wave

    from decompassets.n64 import musyx

    coefficients = [0] * 128
    coefficients[8:16] = [1024] * 8
    first = bytes([12, 0x1f]) + bytes(14)
    second = bytes([12]) + bytes(15)
    encoded = musyx.BOOK.pack(*coefficients) + struct.pack('>4h', 11, 100, -22, -100) + first + second
    asset = {'layout': 'eurocom-samples', 'samples': [
        {'offset': 0, 'rate': 11025, 'samples': 35, 'codec': 'MusyX ADPCM', 'preview_available': True},
    ], 'preview_settings': {'format': 'auto'}, 'reason': 'Validated sample extent'}
    result = eurocom.preview(encoded, asset, {'sample': 0})
    assert result['mime'] == 'audio/wav'
    with wave.open(io.BytesIO(base64.b64decode(result['data_url'].split(',')[1]))) as wav:
        assert wav.getframerate() == 11025 and wav.getnframes() == 35
        pcm = struct.unpack('<35h', wav.readframes(35))
    assert pcm[:4] == (11, 100, 51, 49)
    assert pcm[32:] == (-22, -100, -50)

    with pytest.raises(AssetError, match='truncated'):
        eurocom.preview(encoded[:-1], asset, {'sample': 0})
    invalid = bytearray(encoded)
    invalid[264] = 0x80
    with pytest.raises(AssetError, match='missing predictor'):
        eurocom.preview(invalid, asset, {'sample': 0})


def test_mort_index_uses_header_rates_and_bounds_final_clip():
    count = 8
    base = 36
    stream = struct.pack('>4sHHII', b'MORT', 75, 16000, 4, 0)
    clip_data = base + count * 4
    entries = [0x1000000 | (clip_data - base + i * len(stream) + 4) for i in range(count)]
    image = bytearray(bytes(base - 4) + struct.pack('>I8I', count, *entries) + stream * count)
    asset = eurocom._mort(image, lambda: None)
    assert [(c['offset'], c['size'], c['samples'], c['rate']) for c in asset['samples']] == [
        (clip_data + i * 16, 16, 12000, 16000) for i in range(count)
    ]
    rows, _ = eurocom._records(image, asset)
    assert rows[-1]['duration_seconds'] == 0.75
    assert eurocom._mort(image[:-1], lambda: None) is None
    struct.pack_into('>I', image, clip_data + 8, 5)
    assert eurocom._mort(image, lambda: None) is None
