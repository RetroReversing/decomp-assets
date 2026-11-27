"""Local F3DEX2 meshes in checksum-checked blocks with bounded section offsets."""
import re
import struct

from .. import formats, rnc
from . import display_meshes

LAYOUT = 'rnc-inline-vertex-mesh'
_MAGIC = re.compile(b'RNC[\x01\x02]')
_LIMIT = 256 * 1024


def _state(w0, w1):
    # The list culls against its loaded box and calls a separate segment for
    # render state. Its own triangles are still local; the sublist is omitted.
    return w0 == 0x03000000 or (w0, w1) == (0xde000000, 0x07000000)


def _read(image, at):
    try:
        data, packed = rnc.unpack_at(image, at, max_output=_LIMIT, max_packed=_LIMIT)
    except rnc.RncError:
        return None
    if len(data) < 32:
        return None
    vertices, commands, tail, reserved = struct.unpack_from('>4I', data)
    if (vertices != 16 or reserved or commands < 64 or commands % 8 or (commands-vertices) % 16
            or not commands < tail <= len(data) or tail % 8):
        return None
    mesh = display_meshes.geometry(data, commands, tail, {4: vertices}, vertex_end=commands,
                                   vertex_flag_mask=0xffff, extra_state=_state)
    if mesh is None:
        return None
    return mesh[1], mesh[2], packed


def regions(image, *, check=lambda: None, progress=lambda _: None, **kwargs):
    result = []
    for hit in _MAGIC.finditer(image):
        check()
        at = hit.start()
        mesh = _read(image, at)
        if mesh is None:continue
        vertices, faces, packed = mesh
        result.append(dict(offset=at, size=packed, kind='3d model', media='model', layout=LAYOUT,
                           label='RNC inline local mesh', confidence='validated',
                           vertices=len(vertices), triangles=len(faces),
                           meshes=[dict(name='Mesh 1', vertices=len(vertices), triangles=len(faces))],
                           reason='A checksum-verified block bounds vertices and a closed display list; '
                                  'external state sublists, scene placement and animation are separate.',
                           preview_settings=dict(format='auto', source='rom', offset=at)))
    return result


def preview(image, asset, selection):
    formats.integer(selection.get('mesh', 0), 'Mesh', 0, 0)
    mesh = _read(image, asset['offset'])
    if mesh is None or mesh[2] != asset['size']:
        raise formats.AssetError('The compressed mesh changed. Rescan ROM Explorer.')
    vertices, faces, _ = mesh
    edges = {tuple(sorted((face[i], face[(i+1)%3]))) for face in faces for i in range(3)}
    return dict(media='model', vertices=vertices, triangles=len(faces), edges=sorted(edges),
                points=sorted({i for face in faces for i in face}),
                surfaces=[dict(indices=face, uv=[[0, 0]]*3, colors=[[255, 255, 255, 255]]*3, material=0)
                          for face in faces], materials=[],
                details=dict(format='RNC inline local mesh', vertices=len(vertices), triangles=len(faces)),
                note='Local geometry; external sublists, scene placement, textures and animation are separate.',
                settings=dict(format='auto', source='rom', offset=asset['offset'], mesh=0))
