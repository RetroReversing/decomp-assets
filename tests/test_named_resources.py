import struct

from decompassets.n64 import named_resource_images, named_resource_models, named_resources


def test_named_directory_requires_contiguous_named_members():
    image = bytearray(0x1200)
    struct.pack_into('>I', image, 0x100, 8)
    for index in range(8):
        at = 0x1050+index*16
        pointer = 0x80000400+index*8
        struct.pack_into('>4I', image, 0x104+index*16, pointer, index%2, at, at+16)
        name = f'file{index}'.encode()
        image[0x1000+index*8:0x1000+index*8+len(name)] = name
    assert len(list(named_resources.members(image, lambda: None))) == 8
    image[0x104+3*16+11] ^= 0x10
    assert not list(named_resources.members(image, lambda: None))


def test_named_lz_rejects_invalid_copies_and_honors_its_declared_end():
    payload = bytes.fromhex('83 414243 00 03 e0 00')
    stream = struct.pack('>I', len(payload)+4) + payload + b'padding'
    assert named_resources.unpack(stream) == b'ABCAB\0\0'
    invalid = bytearray(stream)
    invalid[9] = 4
    assert named_resources.unpack(invalid) is None


def test_named_model_uses_the_stored_list_and_vertex_addresses():
    model = bytearray(0x118)
    struct.pack_into('>IIHHII', model, 0, 0x64c8, len(model), 1, 100, 0x100, 0x110)
    struct.pack_into('>II4H', model, 0x100, 0xc0, 0, 0, 0, 0, 0)
    model[0x110:0x115] = b'test\0'
    for index, (x, y) in enumerate(((0, 0), (1, 0), (0, 1))):
        struct.pack_into('>3hH2h4B', model, 0x90+index*16, x, y, 0, 0, 0, 0, 255, 255, 255, 255)
    struct.pack_into('>8I', model, 0xc0, 0xda380003, 0x08000000, 0x01003006, 0x0c000090,
                     0x05000204, 0, 0xdf000000, 0)
    mesh, = named_resource_models._meshes(model)
    assert (mesh['name'], mesh['vertices'], mesh['triangles']) == ('test · Mesh 1', 3, 1)
    struct.pack_into('>I', model, 0xcc, 0x0c000170)
    assert not named_resource_models._meshes(model)


def test_huff_block_rebases_dc_and_transposes_ac_coefficients():
    block = named_resource_images._block
    bits = named_resource_images._Bits(bytes([0b11110000]))
    output = named_resource_images._Writer()
    # DC +1, then a nonzero AC in the first zigzag slot.
    dc = {(1, 1): 1}
    ac = {(1, 1): 1, (1, 0): 0}
    dc_encode = {0: (1, 0)}
    ac_encode = {0x11: (2, 2), 0: (1, 0)}
    block(bits, output, dc, ac, dc_encode, ac_encode, 1)
    assert bits.position == 5
    assert output.finish() == bytes([0b01010111])
