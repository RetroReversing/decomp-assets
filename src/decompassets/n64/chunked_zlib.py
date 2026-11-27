"""Length-delimited, independently checked zlib pages in a bounded container."""
import re
import struct
import zlib

from .. import formats

LAYOUT = 'chunked-zlib-stream'
CODEC = 'chunked zlib'
_PAGE = 16000
_MAX_CHUNKS = 256
_SCAN_BUDGET = 128 * 1024 * 1024
_MAGIC = re.compile(rb'\x78[\x01\x5e\x9c\xda]')


def unpack(image, offset=0, *, check=lambda: None):
    """Return the decoded bytes and exact extent, or None for an invalid container."""
    if offset < 0 or offset+12 > len(image) or offset % 2:
        return None
    packed, expected = struct.unpack_from('>II', image, offset)
    end = offset+packed
    if not (18 <= packed <= formats.MAX_BYTES and 1 <= expected <= formats.MAX_BYTES and end <= len(image)):
        return None
    pos = offset+8
    output = bytearray()
    count = 0
    try:
        while len(output) < expected:
            check()
            if pos+4 > end or count >= _MAX_CHUNKS:
                return None
            size = int.from_bytes(image[pos:pos+4], 'big')
            pos += 4
            if size < 6 or pos+size > end:
                return None
            stream = zlib.decompressobj()
            page = stream.decompress(image[pos:pos+size], min(_PAGE,expected-len(output))+1)
            if not stream.eof or stream.unused_data or stream.unconsumed_tail or not page:
                return None
            remaining = expected-len(output)
            if len(page) != min(_PAGE,remaining):
                return None
            output.extend(page)
            pos += size
            if pos & 1:
                if pos >= end or image[pos] != 0:
                    return None
                pos += 1
            count += 1
    except zlib.error:
        return None
    if pos != end:
        return None
    return bytes(output), packed, count


def regions(image, *, check=lambda: None, **kwargs):
    result = []
    budget = _SCAN_BUDGET
    for hit in _MAGIC.finditer(image):
        check()
        offset = hit.start()-12
        if offset < 0 or offset % 2:
            continue
        packed, expanded, first = struct.unpack_from('>III', image, offset)
        if not (18 <= packed <= formats.MAX_BYTES and 1 <= expanded <= formats.MAX_BYTES
                and 6 <= first <= packed-12 and offset+packed <= len(image)):
            continue
        if expanded > budget:
            break
        budget -= expanded
        record = unpack(image,offset,check=check)
        if not record:
            continue
        _, size, count = record
        result.append(dict(offset=offset, size=size, kind='compressed', layout=LAYOUT,
                           label='Chunked zlib stream', confidence='validated', media='metadata', expanded_size=expanded,
                           chunk_count=count, reason='All page lengths, zlib checksums and total sizes agree.',
                           preview_settings=dict(format='auto', source='rom', offset=offset)))
    return result


def preview(image, asset, selection):
    record = unpack(image,asset['offset'])
    if record is None:
        raise formats.AssetError('The compressed stream changed. Rescan ROM Explorer.')
    data, size, count = record
    return dict(media='metadata', title=asset['label'],
                fields={'Compressed bytes':size,'Decompressed bytes':len(data),'Pages':count},
                note='Use the decompressed source in a manual preview to inspect these bytes.',
                settings=dict(format='auto', source='rom', offset=asset['offset']))
