"""Local F3DEX2 meshes whose vertex batch immediately precedes the list."""
import re
import struct

from . import display_lists, display_meshes

_MARKER = re.compile(rb'\x01[\x00-\x0f][\x00-\xff][\x00-\xfe]\x80')
_MAX_MESHES = 8192


def regions(image, *, check=lambda: None, progress=lambda _: None):
    result = []
    for index, match in enumerate(_MARKER.finditer(image)):
        if index % 256 == 0:
            check()
        at = match.start()
        if at % 8 or at+8 > len(image):
            continue
        first, pointer = struct.unpack_from('>II', image, at)
        count = display_lists._vertex_count(first)
        if not 3 <= count <= 64:
            continue
        vertex_start = at-count*16
        if vertex_start < 0 or vertex_start % 8:
            continue
        mapping = vertex_start-(pointer & 0xffffff)
        parsed = display_meshes.geometry(image, at, min(at+512, len(image)), {0x80: mapping})
        if not parsed:
            continue
        end, vertices, faces = parsed
        if (len(faces) < 2 or any(len({vertex[axis] for vertex in vertices}) < 2 for axis in range(3))):
            continue  # Flat lists can be sprites, not 3D objects.
        result.append(dict(offset=at, size=end-at, kind='3d model', media='model', layout='f3dex-mesh',
                           confidence='inferred', label='Adjacent F3DEX2 local mesh', vertices=len(vertices),
                           triangles=len(faces), address_maps=[(0x80, mapping)],
                           reason='The list follows its vertex batch; all vertex loads and triangle slots resolve before its end.',
                           preview_settings=dict(source='rom', format='auto', offset=at)))
        if len(result) >= _MAX_MESHES:
            break
    return result
