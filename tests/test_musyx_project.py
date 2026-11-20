import struct

from decompassets.n64 import musyx_project


def test_project_requires_exact_song_ids_and_pool_program_links():
    end = b'\xff' * 4
    page = struct.pack('>HBBBB2x', 0x8001, 10, 3, 255, 0) + end * 2
    setup = struct.pack('>HH', 7, 0) + bytes([0, 127, 64, 0, 0, 0, 0, 0]) * 16
    size = 40 + len(page) + 8 + len(setup) + 4
    group = struct.pack('>IHH8I', size, 3, 0, *([32] * 6), 48, 56) + page + end * 2 + setup + end
    project = group + end

    def section(obj):
        return struct.pack('>IH2x', 8, obj) + end

    pool = struct.pack('>4I', 16, 28, 40, 52) + b''.join(section(obj) for obj in (1, 0xc001, 0x4001, 0x8001))
    image = project + pool
    indexed = [(0, 0, 3, 7)]
    result = musyx_project.locate(image, len(image), indexed)
    assert result['end'] == len(project)
    assert result['groups'][3]['setups'][7][0] == (0, 127, 64, 0, 0)
    assert musyx_project.locate(image, len(image), [(0, 0, 3, 8)]) is None
    objects = musyx_project.find_pool(image, result['end'], len(image), {0x8001})
    assert 0x8001 in objects['objects']['layer']
    missing_layer = image[:-12] + section(0x8002)
    assert musyx_project.find_pool(missing_layer, result['end'], len(image), {0x8001}) is None
