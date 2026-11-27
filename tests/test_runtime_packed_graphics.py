import struct

from decompassets.n64 import mwo_graphics, runtime_packed_graphics


def fixture():
    pixels = bytes((i * 29) % 256 for i in range(256))
    packed = b'\1' + len(pixels).to_bytes(4, 'big') + b''.join(
        b'\xff' + pixels[i:i+8] for i in range(0, len(pixels), 8))
    end = (0x100 + len(packed) + 15) & ~15
    image = bytearray(end)
    struct.pack_into('>3I', image, 0x20, 0x80300000, 0x100, end)
    image[0x100:0x100+len(packed)] = packed
    ram = bytearray(4096)
    ram[0x800:0x900] = pixels
    commands = [(0xfd900000, 0x80000800), (0xf5900000, 0x07000000), (0xe6000000, 0),
                (0xf3000000, 0x0707f000), (0xe7000000, 0), (0xf5800800, 0),
                (0xf2000000, (63 << 14) | (7 << 2)), (0xdf000000, 0)]
    for i, (a, b) in enumerate(commands):
        struct.pack_into('>II', ram, i*8, a, b)
    return image, ram


def test_runtime_packed_texture_requires_matching_decoded_pixels():
    image, ram = fixture()
    assets = runtime_packed_graphics.regions(image, [ram])
    assert len(assets) == 1 and assets[0]['offset'] == 0x100
    assert mwo_graphics.preview(image, assets[0], {})['mime'] == 'image/png'
    ram[0x880] ^= 1
    assert not runtime_packed_graphics.regions(image, [ram])


def test_runtime_model_preview_uses_captured_commands_and_matching_vertices():
    image, ram = fixture()
    packed = mwo_graphics.inflate(image[0x100:])[0]
    vertices = bytearray(packed)
    for index, (x, y) in enumerate(((0, 0), (100, 0), (0, 100))):
        struct.pack_into('>3h', vertices, 16*index, x, y, 0)
        vertices[16*index+6:16*index+8] = b'\0\0'
    block = b'\1' + len(vertices).to_bytes(4, 'big') + b''.join(
        b'\xff' + vertices[i:i+8] for i in range(0, len(vertices), 8))
    end = (0x100 + len(block) + 15) & ~15
    image = bytearray(end)
    struct.pack_into('>3I', image, 0x20, 0x80300000, 0x100, end)
    image[0x100:0x100+len(block)] = block
    ram[0x800:0x900] = vertices
    struct.pack_into('>6I', ram, 56, 0x04000c2f, 0x80000800, 0xbf000000, 0x00000204, 0xb8000000, 0)
    assets = runtime_packed_graphics.regions(image, [ram])
    model = next(asset for asset in assets if asset['kind'] == '3d model')
    assert runtime_packed_graphics.preview_model(image, model, {})['triangles'] == 1
    ram[0x810] ^= 1
    assert not any(asset['kind'] == '3d model' for asset in runtime_packed_graphics.regions(image, [ram]))
