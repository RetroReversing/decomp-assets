"""FORM geometry must stay bounded by its filesystem and chunk headers."""
import struct

from decompassets import n64
from decompassets.n64 import mainfs_models

from .test_mainfs import filesystem, form, lz


def model():
    vertices = struct.pack('>HHf', 4, 0, 0.5)
    vertices += b''.join(struct.pack('>hhhbbb', *xyz, 0, 0, 127)
                         for xyz in ((0, 0, 0), (20, 0, 0), (20, 20, 0), (0, 20, 0)))
    faces = struct.pack('>HHI', 1, 0, 0) + b'\x35'
    faces += b''.join(struct.pack('>Hhff', i, 0, float(i & 1), float(i >> 1)) for i in range(4))
    faces += bytes(5)
    return form([(b'VTX1', vertices), (b'FAC1', faces)])


def test_model_found_and_previewed_with_quad_split():
    raw = model()
    image = bytes(0x40) + filesystem([[(1, raw, lz(raw))], []]) + bytes(8)
    found = [a for a in n64.regions(image) if a.get('layout') == mainfs_models.LAYOUT]
    assert len(found) == 1
    preview = n64.preview(image, found[0], {})
    assert preview['vertices'][2] == [10, 10, 0]
    assert [s['indices'] for s in preview['surfaces']] == [[0, 1, 2], [0, 2, 3]]


def test_rejects_truncated_or_invalid_faces():
    raw = model()
    assert mainfs_models.geometry(raw[:-1]) is None
    bad = bytearray(raw)
    pos = bad.index(b'FAC1') + 8 + 8
    bad[pos] = 0x30
    assert mainfs_models.geometry(bytes(bad)) is None
    bad[pos] = 0x35
    struct.pack_into('>H', bad, pos+1, 9)
    assert mainfs_models.geometry(bytes(bad)) is None


def test_final_file_does_not_cover_the_rest_of_the_cartridge():
    raw = model()
    image = bytes(0x40) + filesystem([[], [(1, raw, lz(raw))]]) + bytes(4096)
    found = mainfs_models.regions(image)
    assert len(found) == 1
    assert found[0]['size'] == 8 + len(raw)
    assert found[0]['offset'] + found[0]['size'] < len(image)
