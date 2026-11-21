import struct

import pytest

from decompassets import formats
from decompassets.n64 import iguana_textures, preview

from .test_rnc import literal_block


def fixture(mode):
    colors = 32 if mode=='ci4' else 512
    stride = 2 if mode=='ci4' else 4
    record = struct.pack('<9H4I',0,0,0,0,1,2,2,4,2,stride*2,colors,0,colors)
    index = b'x_bitmap : index set'.ljust(32, b'\0')
    header = index+struct.pack('<III',999,34,0)+b'~~~~'
    directory = index+struct.pack('<III',0xcdcdcdcd,34,1)+bytes(228)
    palette = struct.pack('<H',0xf801)+bytes(colors-2)
    pixels = bytes(stride*2)
    decoded = b'!IgUaNa!'+header+record+b'~~~~'+directory+struct.pack('<III',999,1,0)+b'~~~~'+palette+pixels
    packed = literal_block(decoded)[18:]
    return struct.pack('>4sIIH4xH',b'RNC\x81',len(decoded),len(packed)+(len(packed)%2),1,len(packed))+packed+bytes(len(packed)%2)


@pytest.mark.parametrize('mode',['ci4','ci8'])
def test_discover_and_preview_padded_iguana_bitmap(mode):
    image = fixture(mode)
    asset, = iguana_textures.regions(image)
    result = preview(image,asset,{'texture':0})
    assert result['mime']=='image/png'
    assert result['details']['format']==mode
    assert (result['details']['width'],result['details']['height'])==(2,2)
    with pytest.raises(formats.AssetError):
        preview(image,asset,{'texture':1})
    for damaged in (image[:-5],image[:4]+bytes(4)+image[8:]):
        assert iguana_textures.regions(damaged)==[]


def test_paged_iguana_stream_checks_page_lengths_and_uses_even_alignment():
    pages = [bytes(8192), b'final page']
    packed = [literal_block(page)[18:] for page in pages]
    payload = b''.join(page+bytes(len(page)%2) for page in packed)
    header = struct.pack('>4sIIH4x2H',b'RNC\x81',8202,len(payload),2,*(len(page) for page in packed))
    assert iguana_textures.unpack(header+payload,0) == (b''.join(pages),len(header+payload))
    with pytest.raises(ValueError,match='page exceeds'):
        iguana_textures.unpack(header[:-2]+b'\xff\xff'+payload,0)
