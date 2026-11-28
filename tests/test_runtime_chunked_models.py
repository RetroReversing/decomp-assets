"""Task calls and decoded resources jointly prove local model batches."""
import struct

from decompassets import n64
from decompassets.n64 import runtime_chunked_models


def fixture():
    data = bytearray(0x200)
    for i, point in enumerate(((0, 0, 0), (100, 0, 0), (0, 100, 0), (0, 0, 100))):
        struct.pack_into('>3hH2h4B', data, 0x100+i*16, *point, 0, i*7, i*11, 20+i, 40+i, 60+i, 255)
    commands = [(0x0400103f, 0x01000000), (0xb1000204, 0x00000406),
                (0xb1000602, 0x00020604), (0xb8000000, 0)]
    for i, command in enumerate(commands):
        struct.pack_into('>II', data, 0x20+i*8, *command)
    chunks = [data[i:i+127] for i in range(0, len(data), 127)]
    stream = b'12345' + b''.join(bytes([0x80 | len(chunk)]) + chunk for chunk in chunks) + b'\0'
    offset, headers, body = 36, [], bytearray()
    for _ in range(3):
        headers.append(struct.pack('>III', offset, len(data), 0x80000000 | len(stream)))
        body.extend(stream)
        if len(body) % 2:
            body.append(0)
        offset = 36 + len(body)
    image = b''.join(headers) + body
    ram = bytearray(0x4000)
    ram[0x2000:0x2200] = data
    struct.pack_into('>6I', ram, 0x800, 0xbc000406, 0x80002100,
                     0x06000000, 0x80002020, 0xb8000000, 0)
    task = [1, 0, 0x80000100, 0, 0x80000100, 0, 0x80000100, 0x800, 0, 0, 0, 0, 0x80000800, 24, 0, 0]
    struct.pack_into('>16I', ram, 0x400, *task)
    return image, ram


def test_runtime_chunked_mesh_preview():
    image, ram = fixture()
    assets = runtime_chunked_models.regions(image, [ram])
    assert len(assets) == 3 and len(assets[0]['meshes']) == 1
    result = n64.preview(image, assets[0], {})
    assert result['media'] == 'model' and len(result['vertices']) == 4 and result['triangles'] == 4


def test_rejects_unmatched_task_commands_or_vertices():
    image, ram = fixture()
    for offset in (0x80c, 0x2108):
        changed = bytearray(ram)
        changed[offset] ^= 1
        assert not runtime_chunked_models.regions(image, [changed])
    assert not runtime_chunked_models.regions(image[:-2], [ram])


def test_repeated_frames_are_deduplicated():
    image, ram = fixture()
    assert runtime_chunked_models.regions(image, [ram]) == runtime_chunked_models.regions(image, [ram, ram])


def test_captured_commands_can_be_generated_at_runtime():
    image, ram = fixture()
    changed = bytearray(ram)
    changed[0x2028:0x2038] = ram[0x2030:0x2038] + ram[0x2028:0x2030]
    assets = runtime_chunked_models.regions(image, [changed])
    assert assets and assets[0]['meshes'][0]['command'] == -1
    assert n64.preview(image, assets[0], {})['media'] == 'model'


def test_previous_scan_mesh_metadata_still_previews():
    image, ram = fixture()
    asset = runtime_chunked_models.regions(image, [ram])[0]
    item = asset['meshes'][0]
    item['command_size'] = len(bytes.fromhex(item.pop('captured')))
    item.pop('vertex_digest')
    assert n64.preview(image, asset, {})['media'] == 'model'
