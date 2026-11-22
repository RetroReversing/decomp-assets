import base64
import struct

from decompassets.n64 import fat_textures as texture


def cartridge():
    data = bytearray(0x1000)
    struct.pack_into('>H', data, 4, 3)
    struct.pack_into('>H', data, 8, 2)
    for i in range(3):
        struct.pack_into('>II', data, 156+i*8, 0x200+i*16, 16)
        struct.pack_into('>4I', data, 0x200+i*16, 0x500,0x580,0x600,0x680)
    for i in range(32):
        struct.pack_into('>HHHBBHH', data, 0x300+i*12, i%4,0xffff,0xffff,4,4,1,128)
    data[0x500:0x700] = bytes(range(256))*2
    count = 4
    header = bytearray(4+count*8)
    struct.pack_into('>I',header,0,2)
    cursor = len(header)
    records = bytearray()
    for i in range(count):
        rows = [(0x300+j*12,63,j) for j in range(32)] if i == 0 else [(0x300,63,0)]
        struct.pack_into('>II', header, 4+i*8, cursor, len(rows))
        encoded = b''.join(struct.pack('>IHH',*row) for row in rows)
        cursor += len(encoded);records += encoded
    return bytes(data+header+records)


def test_file_table_previews_indexed_texture():
    image = cartridge()
    assets = texture.regions(image)
    assert len(assets) == 4 and assets[0]['texture_count'] == 32
    assert len({asset['offset'] for asset in assets}) == 4
    result = texture.preview(image, assets[0], {'texture':2})
    assert result['mime'] == 'image/png'
    assert base64.b64decode(result['data_url'].split(',')[1]).startswith(b'\x89PNG')


def test_file_table_rejects_invalid_image_pointers():
    image = bytearray(cartridge())
    struct.pack_into('>I',image,0x200,0xffffffff)
    assert not texture.regions(image)


def test_unpaletted_eight_bit_texture_is_alpha():
    import zlib

    asset = dict(textures=[dict(kind=1, palette=None, alpha=None, width=2, height=2,
                                preview_settings=dict(format='i8',width=2,height=2,offset=0))],
                 preview_settings=dict(source='rom',format='auto',offset=0),reason='Checked descriptor')
    png = base64.b64decode(texture.preview(bytes((0,64,128,255)),asset,{})['data_url'].split(',')[1])
    size = int.from_bytes(png[33:37], 'big')
    raw = zlib.decompress(png[41:41+size])
    assert raw[:9] == bytes((0,255,255,255,0,255,255,255,64))
