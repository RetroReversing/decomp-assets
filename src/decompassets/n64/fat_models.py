"""F3DEX meshes whose display lists and vertices are linked by file-table records."""

import struct

from .. import formats
from . import display_meshes, fat_textures

LAYOUT = 'fat-linked-models'


def _find(maps, level, kind, ref):
    if ref == 0xffff:
        return None
    index = ref & 0x7fff
    for table in ([0] if ref & 0x8000 else [level, 1, 0]):
        if (kind,index) in maps[table]:
            return maps[table][kind,index]
    return None


def _mesh(image, base, end, maps, level, off):
    if not base <= base+off <= end-12:
        return None
    _, tri_ref, vertex_ref, tri_size, vertex_size, _ = struct.unpack_from('>6H',image,base+off)
    tri = _find(maps,level,23,tri_ref)
    vertex = _find(maps,level,22,vertex_ref)
    if (tri is None or vertex is None or not tri_size or tri_size%8 or not vertex_size or vertex_size%16
            or base+tri+tri_size > end or base+vertex+vertex_size > end):
        return None
    parsed = display_meshes.geometry(image,base+tri,base+tri+tri_size,{6:base+vertex},
                                     vertex_end=base+vertex+vertex_size,vertex_flag_mask=0xffff)
    if parsed is None:
        return None
    return tri,vertex,tri_size,vertex_size,parsed[1],parsed[2]


def regions(image, *, check=lambda: None, progress=lambda _: None):
    result = []
    for base, end, tables, _, spans in fat_textures.file_tables(image,check):
        maps = [{(kind,index):off for off,kind,index in table} for table in tables]
        for level, table in enumerate(tables):
            check()
            meshes = []
            for off,kind,index in table:
                if kind != 24:
                    continue
                found = _mesh(image,base,end,maps,level,off)
                if found:
                    tri,vertex,tri_size,vertex_size,vertices,faces = found
                    meshes.append(dict(name=f'Mesh {index}', record=base+off, triangle_offset=base+tri,
                                       triangle_size=tri_size, vertex_offset=base+vertex,vertex_size=vertex_size,
                                       vertices=len(vertices),triangles=len(faces)))
            if meshes:
                start,size = spans[level]
                result.append(dict(offset=start+4,size=size-4,kind='3d model',media='model',layout=LAYOUT,
                                   confidence='validated',label=f'Model table {level+1}',meshes=meshes,
                                   vertices=sum(m['vertices'] for m in meshes),
                                   triangles=sum(m['triangles'] for m in meshes),
                                   reason='The file table links bounded display lists to their vertex arrays. '
                                          'Geometry is shown without scene transforms or textures.',
                                   preview_settings=dict(source='rom',format='auto',offset=start+4)))
    return result


def preview(image, asset, selection):
    index = formats.integer(selection.get('mesh',0),'Mesh',0,len(asset['meshes'])-1)
    item = asset['meshes'][index]
    tri,vertex = item['triangle_offset'],item['vertex_offset']
    if not 0 <= tri < tri+item['triangle_size'] <= len(image) or not 0 <= vertex < vertex+item['vertex_size'] <= len(image):
        raise formats.AssetError('The model records changed. Scan ROM Explorer again.')
    parsed = display_meshes.geometry(image,tri,tri+item['triangle_size'],{6:vertex},
                                     vertex_end=vertex+item['vertex_size'],vertex_flag_mask=0xffff)
    if not parsed or (len(parsed[1]),len(parsed[2])) != (item['vertices'],item['triangles']):
        raise formats.AssetError('The display list changed. Scan ROM Explorer again.')
    _, vertices, faces = parsed
    edges = sorted({tuple(sorted((face[i],face[(i+1)%3]))) for face in faces for i in range(3)})
    return dict(media='model',vertices=vertices,triangles=len(faces),edges=edges,
                points=sorted({v for face in faces for v in face}),materials=[],
                surfaces=[dict(indices=face,uv=[[0,0]]*3,colors=[[255,255,255,255]]*3,material=0)
                          for face in faces],
                details=dict(format='File-table F3DEX mesh',vertices=len(vertices),triangles=len(faces),
                             note=asset['reason']),settings=dict(asset['preview_settings'],mesh=index))
