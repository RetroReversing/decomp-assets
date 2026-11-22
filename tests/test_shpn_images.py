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
