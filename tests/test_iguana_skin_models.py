"""Synthetic typed geometry resource and compact vertex-cache commands."""
import struct

import pytest

from decompassets import formats
from decompassets.n64 import iguana_skin_models

from .test_rnc import literal_block


def _geometry(*, bad_index=False, bad_count=False, with_bone=False):
    header = b'!IgUaNa!' + bytes(44)
    head = bytearray(66)
    command = bytes([1, 0, 0] if with_bone else []) + bytes([2, 0, 0, 3, 0, 3, 0, 1, 3 if bad_index else 2, 0])
    struct.pack_into('<HHHII', head, 0x26, 1, 1, 1, 3, len(command))
    struct.pack_into('<f', head, 0x34, 2.0)
    arrays = [head, b'texture\0\0' + command,
              struct.pack('<16sHIHIH', b'body', 1, 0, 0, 3, 1),
              struct.pack('<7HI', 0, 0, 1, 3, 2 if bad_count else 1, 0, 0, 0),
              b''.join(struct.pack('<3h8x', *p) for p in [(0, 0, 0), (16, 0, 0), (0, 16, 0)])]
    payload = bytearray(header)
    descriptors = []
    for name, array, stride, count in zip(iguana_skin_models._NAMES, arrays, (66, 1, 30, 18, 14), (1, len(arrays[1]), 1, 1, 3)):
        descriptors.append(struct.pack('<32s6I', name, 0xcdcdcdcd, stride, count, 0, 0, len(payload)))
        payload.extend(array)
    payload.extend(b''.join(descriptors))
    return bytes(payload)


def _archive(decoded):
    packed = literal_block(decoded)[18:]
    payload = packed + bytes(len(packed) % 2)
    resource = struct.pack('>4sIIH4xH', b'RNC\x81', len(decoded), len(payload), 1, len(packed)) + payload
    files = [(b'first.dat', b'1234'), (b'model.irc', resource + bytes(2)),
             (b'~audio~\\Music.tbl', b'1234'), (b'~audio~\\Music.ctl', b'5678')]
    directory = b''.join(struct.pack('>I', len(data)) + name + b'\0' for name, data in files)
    return directory + b'\xff'*4 + b''.join(data for _, data in files)


def test_skinned_geometry_resolves_commands_and_rejects_invalid_inputs():
    image = _archive(_geometry())
    asset, = iguana_skin_models.regions(image)
    result = iguana_skin_models.preview(image, asset, {'mesh': 0})
    assert result['vertices'] == [(0, 0, 0), (16, 0, 0), (0, 16, 0)]
    assert result['triangles'] == 1 and result['edges'] == [(0, 1), (0, 2), (1, 2)]
    with pytest.raises(formats.AssetError):
        iguana_skin_models.preview(image, asset, {'mesh': 1})
    assert not iguana_skin_models.regions(_archive(_geometry(bad_index=True)))
    assert not iguana_skin_models.regions(_archive(_geometry(bad_count=True)))


def test_rest_pose_uses_the_loaded_bone_and_precision_scale(monkeypatch):
    monkeypatch.setattr(iguana_skin_models, '_skeleton', lambda data: ([(1.0, 2.0, 3.0)], []))
    _, vertices, faces = iguana_skin_models._geometry(_geometry(with_bone=True))[0]
    assert vertices == [(2.0, 4.0, 6.0), (18.0, 4.0, 6.0), (2.0, 20.0, 6.0)]
    assert faces == [(0, 1, 2)]


def test_skeleton_checks_bone_hierarchy_and_virtual_blends():
    data = bytearray(b'!IgUaNa!' + bytes(44))
    bone_start = len(data)
    for index, pos in enumerate(((0., 0., 0.), (10., 20., 30.))):
        row = bytearray(50)
        struct.pack_into('<3f', row, 20, *pos)
        struct.pack_into('<2H', row, 44, index, 0xffff if index == 0 else 0)
        data.extend(row)
    virtual_start = len(data)
    data.extend(bytes((0, 1, 25)))
    for name, stride, count, start in ((b'skingroup_rbone', 50, 2, bone_start),
                                      (b'skingroup_vbone', 3, 1, virtual_start)):
        data.extend(struct.pack('<32s6I', name, 0xcdcdcdcd, stride, count, 0, 0, start))
    bones, blends = iguana_skin_models._skeleton(bytes(data))
    assert bones[1] == (10., 20., 30.) and blends == [(7.5, 15., 22.5)]
    data[virtual_start+2] = 101
    assert iguana_skin_models._skeleton(bytes(data)) is None
