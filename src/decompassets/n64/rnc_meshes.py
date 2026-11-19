"""Read EMshV010 polygons and delta-encoded positions from RNC mesh records."""

import struct

from ..formats import AssetError, integer

MAGIC = b'EMshV010'
HEADER_SIZE = 32
MAX_VERTICES = 4096
MAX_CORNERS = 16384
MAX_POLYGONS = 4096


def geometry(data):
    """Require complete tables, bounded positions and in-range polygon references."""
    if len(data) < HEADER_SIZE or not data.startswith(MAGIC):
        return None
    polygons,vertices,corners,normals,attributes,uvs,first,second,third = struct.unpack_from('>9H',data,8)
    if not (3<=vertices<=MAX_VERTICES and 1<=polygons<=MAX_POLYGONS and 3<=corners<=MAX_CORNERS):
        return None
    if first+second+third!=polygons or min(attributes,uvs)==0:
        return None
    corner_at=HEADER_SIZE+polygons*5
    position_at=corner_at+corners*6+normals*8+attributes*6+uvs*4
    end=position_at+vertices*6
    # A handful of meshes carry an ATEX extension with two 16-bit fields.
    # Its geometry ends at the same position; the extension is kept opaque.
    if len(data)!=end and (len(data)!=end+8 or data[end:end+4]!=b'ATEX'):
        return None
    refs=list(struct.iter_unpack('>3H',data[corner_at:corner_at+corners*6]))
    if any(position>=vertices or uv>=uvs or attribute>=attributes for position,uv,attribute in refs):
        return None
    points=[];x=y=z=0
    for dx,dy,dz in struct.iter_unpack('>3h',data[position_at:end]):
        x+=dx;y+=dy;z+=dz
        points.append([x,y,z])
    faces=[]
    for at in range(HEADER_SIZE,corner_at,5):
        size,_,_,start=struct.unpack_from('>BBBH',data,at)
        if size not in (3,4) or start+size>corners:
            return None
        face=[ref[0] for ref in refs[start:start+size]]
        # Corners can reuse a position; skip triangles collapsed by the stored indices.
        for index in range(1,size-1):
            triangle=[face[0],face[index],face[index+1]]
            if len(set(triangle))==3:
                faces.append(triangle)
    return (points,faces) if faces else None


def asset(data,offset,extent):
    found=geometry(data)
    if not found:
        return None
    points,faces=found
    mesh=dict(name='Local mesh',vertices=len(points),triangles=len(faces))
    return dict(offset=offset,size=extent,kind='3d model',media='model',label=f'EMsh mesh · 0x{offset:08X}',
                layout='emsh-v010',confidence='validated',vertices=len(points),triangles=len(faces),meshes=[mesh],
                reason='RNC output byte sum, mesh table sizes and polygon references agree.',
                preview_settings=dict(format='auto',source='decoded',offset=0,block_offset=offset))


def preview(data,asset,selection):
    found=geometry(data)
    if not found:
        raise AssetError('The decoded EMsh mesh layout changed. Rescan ROM Explorer.')
    integer(selection.get('mesh',0),'Mesh',0,0)
    vertices,faces=found
    edges=sorted({tuple(sorted((face[i],face[(i+1)%3]))) for face in faces for i in range(3)})
    return dict(media='model',vertices=vertices,edges=edges,points=list(range(len(vertices))),triangles=len(faces),
                surfaces=[dict(indices=face,uv=[[0,0]]*3,colors=[[255,255,255,255]]*3,material=0) for face in faces],
                materials=[],details=dict(format='EMshV010',vertices=len(vertices),triangles=len(faces)),
                note='Local-space geometry. Materials, scene placement and animation are not applied.',
                settings=dict(format='auto',source='rom',offset=asset['offset'],mesh=0))
