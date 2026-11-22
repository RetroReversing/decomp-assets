"""Bounded ROM disk directories with stored or raw-deflate members."""
import re
import struct
import zlib

from .. import formats

MAGIC = b'-==ROMDISK Header - HERE I AM==-'


def members(image, check=lambda: None):
    groups = []
    for hit in re.finditer(re.escape(MAGIC), image):
        base = hit.start()
        if base+48 > len(image):
            continue
        size, directory, count = struct.unpack_from('>3I', image, base+32)
        lo, hi = base+directory, base+directory+size
        if not 1 <= count <= 4096 or not base+48 <= lo < hi <= len(image) or lo+count*4 > hi:
            continue
        rows = []
        for i in range(count):
            check()
            record = base+struct.unpack_from('>I', image, lo+i*4)[0]
            if record < lo+count*4 or record+21 > hi:
                break
            flags, stored, expanded, offset, _ = struct.unpack_from('>5I', image, record)
            end = image.find(b'\0', record+20, min(hi, record+276))
            if (end < 0 or end == record+20 or image[record+20] != ord('/') or flags not in (0, 0x20000000)
                    or not 0 < stored <= 16*1024*1024 or not 0 < expanded <= 16*1024*1024
                    or flags == 0 and stored != expanded or not base+48 <= base+offset < base+offset+stored <= lo):
                break
            try:
                name = bytes(image[record+20:end]).decode('ascii')
            except UnicodeDecodeError:
                break
            rows.append(dict(name=name, offset=base+offset, size=stored, decoded_size=expanded, compressed=bool(flags)))
        if len(rows) == count and len({row['name'].lower() for row in rows}) == count:
            groups.append(rows)
    return groups


def unpack(image, member):
    start, size, expanded = member['offset'], member['size'], member['decoded_size']
    if expanded > formats.MAX_BYTES or not 0 <= start < start+size <= len(image):
        raise formats.AssetError('The archive member exceeds the preview limit.')
    data = image[start:start+size]
    if not member['compressed']:
        return bytes(data)
    decoder = zlib.decompressobj(-15)
    try:
        output = decoder.decompress(data, expanded+1)
    except zlib.error as error:
        raise formats.AssetError('The compressed archive member changed. Rescan ROM Explorer.') from error
    if not decoder.eof or len(output) != expanded or decoder.unused_data:
        raise formats.AssetError('The compressed archive member changed. Rescan ROM Explorer.')
    return output
