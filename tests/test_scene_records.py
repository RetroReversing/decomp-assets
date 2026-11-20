import struct

from decompassets import n64
from decompassets.n64 import scene_records

from .test_rnc_textures import sum_block


def test_path_offsets_and_coordinate_preview():
    path = b'PATH' + struct.pack('>4H', 2, 90, 0, 62)
    path += struct.pack('>H15f', 0, 1., 2., 3., *[0.] * 12)
    path += struct.pack('>H15f', 20, 4., 5., 6., *[0.] * 12)
    asset, = [a for a in n64.regions(sum_block(path)) if a.get('layout') == 'scene-records']
    rows = n64.preview(path, asset, {})['table']['rows']
    assert rows[1] == dict(index=1, tick=20, x=4., y=5., z=6.)
    assert scene_records.layout(path[:10] + b'\0\x03' + path[12:]) is None


def test_cutscene_command_stream_requires_exact_widths():
    script = b'NCS\0' + struct.pack('>iIIIII', -1, 0, 2, 27, 8, 0xABCD)
    assert scene_records.layout(script)[3][-1]['operand_words'] == ['0000ABCD']
    assert scene_records.layout(script[:-4]) is None


def test_level_sector_extents_and_sparse_indices():
    header = bytearray(b'ELv9\0\0\0\1\0\0\0\0ES_1NONE' + bytes(72))
    body = b'SCTR' + struct.pack('>II', 0, 4) + b'SCTR' + struct.pack('>II', 2, 4) + b'ANTX'
    struct.pack_into('>I', header, 20, len(header) + len(body) - 20)
    struct.pack_into('>I', header, 88, 3)
    fields, rows = scene_records.layout(bytes(header) + body)[2:]
    assert fields['Stored sectors'] == 2 and rows[-1]['sector'] == 2
    assert scene_records.layout(bytes(header) + body.replace(b'ANTX', b'JUNK')) is None


def test_atlas_refers_to_pixels_with_a_separate_palette():
    from decompassets.n64 import rnx_atlas

    palette = b'\xf8\x01' * 16
    first = struct.pack('>BBBH', 0, 8, 8, 0) + bytes(32)
    storage = 40 + 2 * len(palette)
    ref = struct.pack('>BHI', 5, 1, storage + 1)
    directory = (struct.pack('>I', 40) + b'\xcd' * 6 + struct.pack('>I', storage)
                 + struct.pack('>BBII', 1, 1, 64, storage + len(first))
                 + struct.pack('>BBII', 1, 1, 64, storage + len(first) + len(ref)) + b'\xcd' * 6)
    blob = directory + palette * 2 + first + ref
    items = rnx_atlas.layout(blob)
    assert len(items) == 2
    assert items[1]['preview_settings']['palette_offset'] == 72
    assert items[1]['preview_settings']['offset'] == storage + 5
    item = rnx_atlas.asset(items, 0, len(blob))
    assert item['texture_groups'] == [(0, [0]), (1, [0])]
    assert rnx_atlas.preview(blob, item, {'texture': 1})['data_url'].startswith('data:image/png;base64,')
