import struct

from decompassets.n64 import borg


def _archive():
    # Type 8 stores the RGBA palette before its index data.
    texture = struct.pack('>4HII', 4, 8, 1, 0, 16, 528)+bytes(512)+bytes(8)
    count = 32
    payload = texture*count
    rows = b''.join(struct.pack('>HHIII', 8, 0, len(texture), len(texture), i*len(texture))
                    for i in range(count))
    return payload+struct.pack('>II', count, len(payload))+rows


def test_borg_directory_and_texture_preview():
    rom = _archive()
    assets = borg.regions(rom)
    assert len(assets) == 32
    result = borg.preview(rom, assets[0], {})
    assert result['details']['width'] == 8
    assert result['data_url'].startswith('data:image/png;base64,')
    assert not borg.regions(rom[:-1])
