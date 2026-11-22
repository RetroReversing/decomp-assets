import gzip
import struct

from decompassets.n64 import relative_directory


def directory():
    base = 16
    image = bytearray(base + 256 + 8 * 8)
    struct.pack_into('>I', image, base, 256)
    for i in range(8):
        struct.pack_into('>I', image, base + 4 * i, 256 + 8 * i)
        struct.pack_into('>I', image, base + 128 + 4 * i, 1)
        start = len(image) - base
        image.extend(gzip.compress(bytes([i + 1]) * 32, mtime=0))
        end = len(image) - base
        struct.pack_into('>2I', image, base + 256 + 8 * i, start, end)
    return image, base


def test_finds_checked_relative_tables():
    image, base = directory()
    [(found, tables)] = relative_directory.tables(image)
    assert found == base
    a, b = tables[0]
    assert relative_directory.unpack(image, base + a, base + b) == bytes([1]) * 32


def test_rejects_out_of_bounds_or_corrupted_resources():
    image, base = directory()
    struct.pack_into('>I', image, base + 256 + 4, len(image) + 1)
    assert not list(relative_directory.tables(image))
    image, base = directory()
    for i in range(8):
        start, = struct.unpack_from('>I', image, base + 256 + 8 * i)
        image[base + start + 10] ^= 0xff
    assert not list(relative_directory.tables(image))


def test_texture_references_require_a_tile_and_dimensions():
    from decompassets.n64.relative_textures import references

    commands = struct.pack('>6I', 0xfd000000, 7, 0xf5100000, 0, 0xf2000000, (31 * 4 << 12) | 15 * 4)
    assert references(commands, 8) == {7: {((0, 2), 32, 16)}}
    assert not references(commands, 7)
    assert not references(commands[:8] + b'\x00' * 8 + commands[16:], 8)


def test_scans_memory_mapped_images(tmp_path):
    import mmap

    image, _ = directory()
    path = tmp_path / 'image.bin'
    path.write_bytes(image)
    with path.open('rb') as source, mmap.mmap(source.fileno(), 0, access=mmap.ACCESS_READ) as mapped:
        assert len(list(relative_directory.tables(mapped))) == 1


def test_texture_region_and_preview_from_relative_tables():
    from decompassets.n64.relative_textures import preview, regions

    base = 16
    active = [0, 1, 2, 3, 4, 5, 6, 25]
    image = bytearray(base + 256 + 8 * len(active))
    for i, table in enumerate(active):
        table_offset = 256 + 8 * i
        struct.pack_into('>I', image, base + 4 * table, table_offset)
        struct.pack_into('>I', image, base + 128 + 4 * table, 1)
        if table == 1:
            data = struct.pack('>6I', 0xfd000000, 0, 0xf5100000, 0,
                               0xf2000000, (31 * 4 << 12) | 15 * 4)
        elif table == 25:
            data = b'\xff\xff' * (32 * 16)
        else:
            data = bytes([table + 1]) * 32
        start = len(image) - base
        image.extend(gzip.compress(data, mtime=0))
        struct.pack_into('>2I', image, base + table_offset, start, len(image) - base)
    [asset] = regions(image)
    assert (asset['width'], asset['height'], asset['format']) == (32, 16, 'rgba5551-be')
    result = preview(image, asset, {})
    assert result['media'] == 'image'
    assert result['details']['width'] == 32


def test_indexed_texture_requires_the_following_palette_load():
    from decompassets.n64.relative_textures import indexed_references

    commands = struct.pack('>12I', 0xfd000000, 2, 0xf5400000, 0,
                           0xf2000000, (31 * 4 << 12) | 15 * 4,
                           0xfd000000, 3, 0xf0000000, 15 << 14, 0xdf000000, 0)
    assert indexed_references(commands, 4) == {2: {((2, 0), 32, 16, 3)}}
    assert not indexed_references(commands, 3)
    bad = bytearray(commands)
    struct.pack_into('>I', bad, 36, 14 << 14)
    assert not indexed_references(bad, 4)
    bad = bytearray(commands)
    struct.pack_into('>I', bad, 16, 0xdf000000)
    assert not indexed_references(bad, 4)
