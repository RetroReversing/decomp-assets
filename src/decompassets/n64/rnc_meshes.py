"""Read EMshV010 polygons and delta-encoded positions from RNC mesh records."""

import struct

from ..formats import AssetError, integer
from ..formats import preview as image_preview

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
    uv_at=corner_at+corners*6+normals*8+attributes*6
    position_at=uv_at+uvs*4
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
    coordinates=list(struct.iter_unpack('>2h',data[uv_at:position_at]))
    faces=[]
    start=0
    for at in range(HEADER_SIZE,corner_at,5):
        size,texture,_,normal=struct.unpack_from('>BBBH',data,at)
        if size not in (3,4) or start+size>corners or normal>=normals:
            return None
        face=refs[start:start+size]
        start+=size
        # Corners can reuse a position; skip triangles collapsed by the stored indices.
        for index in range(1,size-1):
            triangle=[face[0],face[index],face[index+1]]
            positions=[corner[0] for corner in triangle]
            if len(set(positions))==3:
                faces.append((positions,[coordinates[corner[1]] for corner in triangle],texture))
    return (points,faces) if faces and start==corners else None


def asset(data,offset,extent):
    found=geometry(data)
    if not found:
        return None
    points,faces=found
    mesh=dict(name='Local mesh',vertices=len(points),triangles=len(faces))
    return dict(offset=offset,size=extent,kind='3d model',media='model',label=f'EMsh mesh · 0x{offset:08X}',
                layout='emsh-v010',texture_ids=sorted({texture for _,_,texture in faces if texture!=255}),
                confidence='validated',vertices=len(points),triangles=len(faces),meshes=[mesh],
                reason='RNC output byte sum, mesh table sizes and polygon references agree.',
                preview_settings=dict(format='auto',source='decoded',offset=0,block_offset=offset))


def preview(data,asset,selection,bank=None):
    found=geometry(data)
    if not found:
        raise AssetError('The decoded EMsh mesh layout changed. Rescan ROM Explorer.')
    integer(selection.get('mesh',0),'Mesh',0,0)
    vertices,faces=found
    materials=[]
    slots={}
    sizes={}
    if bank is not None:
        from . import rnc_textures
        texture_data,texture_offset=bank
        textures=rnc_textures.layout(texture_data) or []
        image_bytes=0
        for texture in sorted({texture for _,_,texture in faces}):
            slots[texture]=len(materials)
            material=dict(name=f'Texture {texture}',state='unresolved',wrap='repeat')
            materials.append(material)
            if texture==255:
                material.update(name='Runtime material',state='untextured')
            elif texture<len(textures):
                settings=textures[texture]['preview_settings']
                rendered=image_preview(texture_data,settings)['data_url']
                image_bytes+=len(rendered)
                if image_bytes>16*1024*1024:
                    material.update(state='unsupported',error='Texture image response exceeds 16 MiB.')
                    continue
                sizes[texture]=settings['width'],settings['height']
                material.update(state='linked',offset=texture_offset,image=rendered)
    surfaces=[]
    edges=set()
    for face,coordinates,texture in faces:
        width,height=sizes.get(texture,(1,1))
        uv=[[(u+16384)/(64*width),(v+16384)/(64*height)] for u,v in coordinates] if texture in sizes else [[0,0]]*3
        surfaces.append(dict(indices=face,uv=uv,colors=[[255,255,255,255]]*3,material=slots.get(texture,0)))
        edges.update(tuple(sorted((face[i],face[(i+1)%3]))) for i in range(3))
    note='Local-space geometry. Scene placement and runtime material effects are not applied.'
    if not sizes:
        note+=' No texture bank could be resolved from the resource tables.'
    return dict(media='model',vertices=vertices,edges=sorted(edges),points=list(range(len(vertices))),triangles=len(faces),
                surfaces=surfaces,materials=materials,details=dict(format='EMshV010',vertices=len(vertices),triangles=len(faces)),
                note=note,settings=dict(format='auto',source='rom',offset=asset['offset'],mesh=0))
