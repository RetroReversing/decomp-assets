import struct

from decompassets.n64 import eurocom, musyx_project


def _fixture():
    end = b'\xff' * 4
    page = struct.pack('>HBBBB2x', 1, 10, 3, 255, 0) + end * 2
    setups = b''.join(struct.pack('>HH', i, 0) + bytes([0, 127, 64, 0, 0, 0, 0, 0]) * 16 for i in range(8))
    size = 40 + len(page) + 8 + len(setups) + 4
    group = struct.pack('>IHH8I', size, 3, 0, *([32] * 6), 48, 56) + page + end * 2 + setups + end
    project = group + end
    pool = struct.pack('>4I', 16, 28, 32, 36) + struct.pack('>IH2x', 8, 1) + end * 4
    first_track, region_table, stream, channels = 280, 304, 308, 332
    song = (struct.pack('>6I', 24, region_table, channels, 0, 120, 0)
            + struct.pack('>64I', first_track, *([0] * 63))
            + struct.pack('>IBBHhh', 0, 255, 0, 0, 0, 0)
            + struct.pack('>IBBHhh', 96, 255, 0, 0, -1, 0)
            + struct.pack('>I3I', stream, 8, 0, 0)
            + struct.pack('>HBBHHBBH', 0, 60, 100, 72, 72, 255, 255, 0) + bytes(64))
    bank_offset = 128 + len(project) + len(pool) + 12
    song_offset = bank_offset + 16
    index = b''.join(struct.pack('>IIHHI', song_offset, song_offset + len(song), 3, i, 0) for i in range(8))
    image = index + project + pool + bytes(12) + bytes(16) + song
    return image, dict(offset=bank_offset, bank_end=song_offset), len(index) + len(project)


def test_standalone_music_requires_linked_project_and_pool():
    image, bank, pool_start = _fixture()
    asset = eurocom._standalone_music(image, bank, lambda: None)
    assert asset['layout'] == 'eurocom-songs' and len(asset['songs']) == 8
    assert asset['sample_index'] == bank['offset']
    pool = musyx_project.find_pool(image, pool_start, bank['offset'], {1})
    assert pool['objects']['keymap'] == {} and pool['objects']['layer'] == {}
    assert musyx_project.find_pool(image, pool_start, bank['offset'], {2}) is None
    broken = bytearray(image)
    struct.pack_into('>H', broken, 10, 99)
    assert eurocom._standalone_music(bytes(broken), bank, lambda: None) is None
