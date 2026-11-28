"""Packed model groups: synthetic vertices and commands, never game data."""
import struct

import pytest

from decompassets import n64
from decompassets.n64 import ffs_models

from .test_packed_filesystems import chunked, filesystem


def command(op, first=0, arguments=b'\0\0\0'):
    return struct.pack('>I', first) + arguments + bytes([op])


def cub():
    vertices = b''.join(struct.pack('>3h10x', *point) for point in
                        [(0, 0, 0), (10, 0, 0), (10, 10, 0), (0, 10, 0), (0, 0, 10)])
    commands = b''.join([
        command(11), command(1, 0, b'\0\0\x04'),
        command(3, 0, b'\x01\x02\x03'),
        command(1, 2, b'\0\0\x03'), command(2, 0, b'\x00\x01\x02'),
    ])
    group = bytes(40) + struct.pack('>5I', 5, 5, 0, 0, 0) + vertices + commands
    return b'CUB\0' + struct.pack('>I', 1) + group + b'trailing directory'


def test_packed_model_batches_are_previewed():
    image = bytes(64) + chunked(filesystem([cub()]))
    found = ffs_models.regions(image)
    assert len(found) == 1
    assert found[0]['meshes'][0]['triangles'] == 3
    shown = n64.preview(image, found[0], {})
    assert shown['vertices'][4] == (0, 0, 10)
    assert [s['indices'] for s in shown['surfaces']] == [(0, 1, 2), (0, 2, 3), (2, 3, 4)]
    assert any(asset.get('layout') == ffs_models.LAYOUT for asset in n64.regions(image))
    with pytest.raises(n64.AssetError):
        n64.preview(image, found[0], {'mesh': 1})


def test_bad_indices_and_truncated_commands_are_rejected():
    data = bytearray(cub())
    at = 8 + 60 + 5 * 16
    data[at + 2*8 + 6] = 4
    assert ffs_models.meshes(data) is None
    assert ffs_models.meshes(cub()[:at + 4*8]) is None
