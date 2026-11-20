"""Checked RNX streams and the resources they contain."""

import re
import struct

from .. import formats, rnc
from . import rnc_meshes, rnc_textures, rnx_atlas

MAGIC = re.compile(rb'RNX\x01|FILL')
CODEC = 'RNX byte-sum stream'
PAGE = 0x4000
MAX_OUTPUT = formats.MAX_BYTES
MAX_SCAN_OUTPUT = 128 * 1024 * 1024


def unpack(image, offset=0, *, max_output=MAX_OUTPUT, check=lambda: None, charge=lambda _: None):
    """Decode independently checked pages up to a final RNC/FILL chunk and END!."""
    if not 0 <= offset <= len(image) - 8:
        raise rnc.RncError('RNX offset is outside the image.')
    cursor = offset
    chunks = []
    total = 0
    limit = min(len(image), offset + formats.MAX_BYTES)
    while cursor + 8 <= limit:
        check()
        tag = image[cursor:cursor + 4]
        if tag == b'FILL':
            size, fill, reserved = struct.unpack_from('>HBB', image, cursor + 4)
            if not size or reserved:
                break
            following = cursor + 8
        elif tag in (b'RNX\1', b'RNC\1') and cursor + 18 <= limit:
            size, packed = struct.unpack_from('>II', image, cursor + 4)
            if not 0 < size <= PAGE or (tag == b'RNX\1' and size != PAGE) or not 2 <= packed <= PAGE + 64:
                break
            payload_end = cursor + 18 + packed
            following = cursor + ((18 + packed + 7) & ~7)
            if following > limit or any(image[payload_end:following]):
                break
        else:
            break
        total += size
        if total > max_output:
            raise rnc.RncError('RNX expands beyond the output limit.')
        charge(size)
        if tag == b'FILL':
            decoded = bytes((fill,)) * size
        else:
            decoded = rnc.unpack_sum32(b'RNC\1' + image[cursor + 4:payload_end], max_output=size)
        chunks.append(decoded)
        cursor = following
        if image[cursor:cursor + 4] == b'END!' and cursor + 4 <= limit:
            if tag != b'RNX\1' and (len(chunks) > 1 or tag == b'FILL'):
                return b''.join(chunks), cursor + 4 - offset
            break
        if tag == b'RNC\1':
            break
    raise rnc.RncError('RNX stream has an invalid page boundary or is missing its END! marker.')


def regions(image, *, check=lambda: None, progress=lambda _: None):
    assets = []
    covered = expanded = 0
    def charge(size):
        nonlocal expanded
        expanded += size

    for index, match in enumerate(MAGIC.finditer(image)):
        check()
        offset = match.start()
        if offset < covered or offset % 4:
            continue
        if index % 32 == 0:
            progress(dict(phase='Checking chained RNX resources', done=offset, total=len(image)))
        if index >= 8192 or expanded >= MAX_SCAN_OUTPUT:
            break
        try:
            data, extent = unpack(image, offset, max_output=min(MAX_OUTPUT, MAX_SCAN_OUTPUT - expanded), check=check, charge=charge)
        except rnc.RncError:
            continue
        covered = offset + extent
        items = rnc_textures.layout(data)
        if items:
            asset = rnc_textures.asset(items, offset, extent)
        elif tiles := rnx_atlas.layout(data):
            asset = rnx_atlas.asset(tiles, offset, extent)
        elif mesh := rnc_meshes.asset(data, offset, extent):
            asset = mesh
        else:
            level = data.startswith(b'ELv9\0\0\0\1\0\0\0\0ES_1')
            asset = dict(offset=offset, size=extent, kind='container' if level else 'compressed',
                         confidence='validated', media='metadata', layout='rnx-stream',
                         label='ELv9 level resource' if level else 'RNX resource',
                         preview_settings=dict(format='auto', source='decoded', offset=0, block_offset=offset))
        asset['reason'] = 'RNX page extents, output byte sums and the stream terminator passed validation.'
        asset['decoded_size'] = len(data)
        assets.append(asset)
    return assets


def preview(data, asset):
    fields = {'Decoded bytes': len(data), 'Stored bytes': asset['size']}
    if data[:4].isascii() and data[:4].isalnum():
        fields['Payload signature'] = data[:4].decode('ascii')
    return dict(media='metadata', title=asset['label'], fields=fields, note=asset['reason'],
                settings=dict(format='auto', source='rom', offset=asset['offset']))
