import struct

from decompassets import formats, n64


def fixture():
    name = b'IMAGE______\0'
    pixels = bytes(range(16))
    palette = b''.join(struct.pack('>H', i*2+1) for i in range(256))
    size = 36+len(pixels)+len(palette)
    header = b'T'+size.to_bytes(3, 'big')+struct.pack('>9I', 0,256,8,21,8,2,0,0,0)
    return bytes(16)+name+header+pixels+palette


def test_inline_texture_row_order_and_bounds():
    data = fixture()
    assets = [a for a in n64.regions(data) if a.get('layout') == 'embedded-indexed']
    assert len(assets) == 1
    preview = n64.preview(data, assets[0], {})
    pixels = bytes(range(8))+bytes(range(12,16))+bytes(range(8,12))
    palette = data[-512:]
    expected = formats.preview(pixels+palette, dict(source='rom', offset=0, format='ci8', width=8, height=2,
                               palette_offset=16, palette_format='rgba5551-be'))
    assert preview['data_url'] == expected['data_url']
    assert not any(a.get('layout') == 'embedded-indexed' for a in n64.regions(data[:-1]))


def test_ci4_palette_selection_and_odd_row_swap():
    name = b'IMAGE______\0'
    pixels = bytes(range(16))
    palette = b''.join(struct.pack('>H', i*2+1) for i in range(32))
    size = 36+len(pixels)+len(palette)
    header = b'T'+size.to_bytes(3, 'big')+struct.pack('>9I', 0,32,4,37,16,2,0,0,0)
    data = bytes(16)+name+header+pixels+palette
    asset, = [a for a in n64.regions(data) if a.get('layout') == 'embedded-indexed']
    assert asset['palettes'] == 2
    first = n64.preview(data, asset, {'palette': 0})
    second = n64.preview(data, asset, {'palette': 1})
    assert first['data_url'] != second['data_url']
