import base64

from decompassets.n64 import shpn_images


def literal(data):
    stream = bytearray(b'\x10\xfb' + len(data).to_bytes(3, 'big'))
    while len(data) >= 4:
        n = min(len(data)//4*4, 112)
        stream.append(0xe0+(n-4)//4)
        stream.extend(data[:n])
        data = data[n:]
    stream.append(0xfc+len(data))
    return bytes(stream + data)


def fixture():
    image = bytearray(b'SHPN\0\0\0\0\0\0\0\x01GIMXtest\0\0\0\x18')
    image.extend(b'\x63\0\0\x18\0\x04\0\x04'+bytes(8))
    image.extend(b'\x01\x23\x45\x67\x89\xab\xcd\xef')
    image.extend(b'\x27\0\0\0\0\x10\0\x01\0\x10'+bytes(6))
    image.extend(b'\xff\xff' * 16)
    image[4:8] = len(image).to_bytes(4, 'big')
    return image


def test_indexed_texture_preview_and_bounds():
    data = fixture()
    image = literal(data)
    bank, = shpn_images.regions(image)
    result = shpn_images.preview(image, bank, {})
    assert result['details']['width'] == 4
    assert base64.b64decode(result['data_url'].split(',')[1]).startswith(b'\x89PNG')
    data[20:24] = (99999).to_bytes(4, 'big')
    assert shpn_images.regions(literal(data)) == []


def test_rejects_wrong_palette_size():
    data = fixture()
    data[24+24+4:24+24+6] = b'\0\x08'
    assert shpn_images.frames(data) == []


def shared_palette_fixture():
    image_at = 40
    pal_at = image_at+20
    cpal_at = pal_at+16+512
    data = bytearray(b'SHPN'+bytes(4)+(3).to_bytes(4,'big')+b'GIMX')
    for name,at in ((b'body',image_at),(b'pal ',pal_at),(b'cpal',cpal_at)):
        data.extend(name+at.to_bytes(4,'big'))
    data.extend(b'\x66\0\0\0\0\x02\0\x02'+bytes(8)+bytes([0,1,1,0]))
    for first in (bytes.fromhex('f801'),bytes.fromhex('07c1')):
        data.extend(b'\x27\0\0\0\x01\x00\0\x01'+bytes(8)+first+bytes(510))
    data[4:8] = len(data).to_bytes(4,'big')
    return data


def test_named_shared_palettes_and_zero_sized_images():
    from .test_rom_assets import pixels

    raw = shared_palette_fixture()
    bank, = shpn_images.regions(literal(raw))
    assert bank['frames'] == 1 and bank['palettes'] == 2
    one = shpn_images.preview(literal(raw),bank,{'palette':0})
    two = shpn_images.preview(literal(raw),bank,{'palette':1})
    assert pixels(base64.b64decode(one['data_url'].split(',')[1]))[:4] == bytes([255,0,0,255])
    assert pixels(base64.b64decode(two['data_url'].split(',')[1]))[:4] == bytes([0,255,0,255])
    raw[36:40] = (61).to_bytes(4,'big')  # overlapping/out-of-order palette entry
    assert not shpn_images.frames(raw)


def test_zero_size_without_a_named_palette_is_not_guessed():
    raw = shared_palette_fixture()
    raw[24:28] = b'xxxx'
    assert not shpn_images.frames(raw)


def test_raw_banks_keep_independent_bounds_and_support_shared_palettes():
    first, second = fixture(), shared_palette_fixture()
    data = b'prefix' + first + b'padding' + second + b'after'
    banks = [bank for bank in shpn_images.regions(data) if bank['layout'] == shpn_images.RAW_LAYOUT]
    assert len(banks) == 2 and banks[0]['size'] == len(first) and banks[1]['palettes'] == 2
    for bank in banks:
        result = shpn_images.preview(data, bank, {})
        assert result['media'] == 'image'
    broken = bytearray(data)
    broken[banks[0]['offset']+4:banks[0]['offset']+8] = (99999999).to_bytes(4, 'big')
    assert not any(bank['offset'] == len(b'prefix') for bank in shpn_images.regions(broken))


def test_raw_magic_inside_compressed_stream_is_not_a_second_bank():
    packed = literal(fixture())
    banks = shpn_images.regions(packed)
    assert len(banks) == 1 and banks[0]['layout'] == shpn_images.LAYOUT


def test_odd_width_rows_keep_their_byte_padding():
    raw = fixture()
    raw[24+4:24+8] = b'\x00\x03\x00\x03'
    # The original eight-byte allocation contains six packed bytes, two per row.
    bank, = shpn_images.regions(raw)
    result = shpn_images.preview(raw, bank, {})
    assert result['details']['width'] == result['details']['height'] == 3
    assert result['details']['bytes'] == 6


def test_independently_compressed_pixels_decode_with_inline_palette():
    raw = fixture()
    pixels = bytes(raw[40:48])
    packed = literal(pixels)
    image = raw[:40] + packed + raw[48:]
    image[24] = 0xe3
    image[25:28] = (16+len(packed)).to_bytes(3, 'big')
    image[4:8] = len(image).to_bytes(4, 'big')
    bank, = shpn_images.regions(image)
    result = shpn_images.preview(image, bank, {})
    assert result['details']['width'] == result['details']['height'] == 4
    assert base64.b64decode(result['data_url'].split(',')[1]).startswith(b'\x89PNG')
    image[40] = 0
    assert not shpn_images.regions(image)
