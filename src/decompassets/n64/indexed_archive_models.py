"""Self-contained display-list meshes inside indexed runtime archive members."""
import re

from .. import formats
from . import display_meshes, indexed_runtime_archive

LAYOUT = 'indexed-archive-meshes'
_VERTEX = re.compile(rb'\x01...\x03...', re.S)


def meshes(data, check=lambda: None):
    result=[]
    accepted_end=0
    for match in _VERTEX.finditer(data):
        at=match.start()
        if at%8 or at<accepted_end:continue
        check()
        parsed=display_meshes.geometry(data,at,len(data),{3:0},vertex_end=at)
        if parsed is None:continue
        end,vertices,faces=parsed
        accepted_end=end
        result.append(dict(offset=at,size=end-at,vertices=len(vertices),triangles=len(faces)))
    return result


def regions(image, *, check=lambda: None, **kwargs):
    result=[]
    for row in indexed_runtime_archive.members(image,check):
        check()
        if not row['compressed'] or row['vram']>>24 not in (3,4,5,11):continue
        try:data=indexed_runtime_archive.unpack(image,row)
        except formats.AssetError:continue
        found=meshes(data,check)
        if not found:continue
        listed=[dict(label=f'Mesh {i+1}',**item) for i,item in enumerate(found)]
        result.append(dict(offset=row['start'],size=row['end']-row['start'],compressed=True,kind='3d model',media='model',
                           layout=LAYOUT,confidence='validated',label=f'Archive member {row["index"]} meshes',
                           meshes=listed,nodes=len(listed),triangles=sum(x['triangles'] for x in listed),
                           reason='A bounded archive member contains closed display lists whose vertex and triangle references resolve.',
                           preview_settings=dict(format='auto',source='rom',offset=row['start'],mesh=0)))
    return result


def preview(image,asset,selection):
    row=dict(start=asset['offset'],end=asset['offset']+asset['size'],compressed=True)
    data=indexed_runtime_archive.unpack(image,row)
    found=meshes(data)
    if not found:raise formats.AssetError('The archive model changed. Rescan ROM Explorer.')
    index=formats.integer(selection.get('mesh',0),'Mesh',0,len(found)-1)
    record=dict(found[index],label=asset['label'],address_maps={3:0},vertex_end=found[index]['offset'],
                preview_settings=dict(asset['preview_settings'],mesh=index))
    return display_meshes.preview(data,record,selection)
