"""Archive mesh evidence uses only captured commands and CRC-checked vertices."""

import io
import struct
import zipfile

import pytest

from decompassets import archives, formats, n64
from decompassets.n64 import runtime_zip_models


def fixture(*, planar=False, oblique=False, duplicate=False, invalid_slot=False, short=False, unused=False):
    points = ((0,0,0,1), (20,0,20,2), (0,20,20,3), (10,10,20,4)) if oblique else (
        (0,0,0,1), (20,0,0,2), (0,20,0,3), (0,0,0 if planar else 20,4))
    vertices = b''.join(struct.pack('>hhhHhhBBBB', x, y, z, flag, 30, 40, 255, 128, 64, 255)
                        for x,y,z,flag in points)
    data = bytes(32)+vertices+(vertices if duplicate else b'')
    out = io.BytesIO()
    with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('mesh.bin', data)
    image = bytes(64)+out.getvalue()
    ram = bytearray(2048)
    ram[0x100:0x140] = vertices
    commands = [(0x01004008, 0x80000100), (0x05000204, 0),
                (0x05000204 if unused else 0x05000406, 0),
                (0x05000204 if unused else 0x05000608 if invalid_slot else 0x05000602, 0)]
    if short:
        commands.pop()
    commands.append((0xdf000000,0))
    for index, command in enumerate(commands):
        struct.pack_into('>II', ram, 0x200+index*8, *command)
    return image, bytes(ram)


def test_archive_vertex_batch_is_previewed_with_nonzero_flags():
    image, ram = fixture()
    assets = runtime_zip_models.regions(image, [ram])
    assert len(assets) == 1 and len(assets[0]['meshes']) == 1
    result = n64.preview(image, assets[0], {})
    assert result['media'] == 'model' and len(result['vertices']) == 4 and result['triangles'] == 3
    assert 'scene placement' in result['note']
    member = archives.zip_members(image)[0]
    damaged = bytearray(image)
    damaged[member['payload']] ^= 0x80
    with pytest.raises(formats.AssetError):
        n64.preview(bytes(damaged), assets[0], {})


def test_same_batch_at_another_ram_address_is_not_duplicated():
    image, ram = fixture()
    relocated = bytearray(ram)
    relocated[0x300:0x340] = relocated[0x100:0x140]
    struct.pack_into('>I', relocated, 0x204, 0x80000300)
    assets = runtime_zip_models.regions(image, [ram, bytes(relocated)])
    assert len(assets) == 1 and len(assets[0]['meshes']) == 1


@pytest.mark.parametrize('case', ['planar', 'oblique', 'unused', 'duplicate', 'invalid_slot', 'short', 'changed_vertices'])
def test_unproven_batches_are_not_classified(case):
    image, ram = fixture(planar=case == 'planar', oblique=case == 'oblique', duplicate=case == 'duplicate',
                         invalid_slot=case == 'invalid_slot', short=case == 'short', unused=case == 'unused')
    if case == 'changed_vertices':
        altered = bytearray(ram)
        altered[0x102] ^= 1
        ram = bytes(altered)
    assert runtime_zip_models.regions(image, [ram]) == []


def test_cancellation_is_propagated():
    image, ram = fixture()
    def stop():
        raise RuntimeError('Stopped')
    with pytest.raises(RuntimeError, match='Stopped'):
        runtime_zip_models.regions(image, [ram], check=stop)
