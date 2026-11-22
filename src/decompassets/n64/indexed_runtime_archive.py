"""Bounded indexed cartridge files with paired runtime address ranges."""
import struct
import zlib

from .. import formats

# Archive layout and LZ controls: https://github.com/PandaPandel/Goemons-Great-Adventure-Decomp
MAGIC = b'Nisitenma-Ichigo'
_MAX_FILES = 4096


def members(image, check=lambda: None):
    """Require a monotone offset table, its terminator and paired runtime ranges."""
    at = image.find(MAGIC)
    if at < 0 or at+24 > len(image):
        return []
    offset = at+len(MAGIC)
    previous = None
    entries = []
    for i in range(_MAX_FILES+1):
        check()
        if offset+4*i+4 > len(image):return []
        word = struct.unpack_from('>I', image, offset+4*i)[0]
        value = word & 0x7fffffff
        if not value:
            break
        if value > len(image) or previous is not None and value < previous:
            return []
        entries.append(word)
        previous = value
    else:
        return []
    count = len(entries)-1
    ranges = at-4-8*count
    if count < 16 or ranges < 0 or any(image[at-4:at]):
        return []
    result = []
    for i in range(count):
        lo,hi = entries[i]&0x7fffffff, entries[i+1]&0x7fffffff
        start,end = struct.unpack_from('>II',image,ranges+8*i)
        if start>end or hi<lo or hi>len(image):return []
        if lo==hi:continue
        compressed = bool(entries[i]>>31)
        if compressed:
            if lo+4>hi:return []
            header=struct.unpack_from('>I',image,lo)[0]
            length=header&0x7fffffff
            if length<4 or length>hi-lo or hi-lo-length>1:return []
        result.append(dict(index=i+1,start=lo,end=hi,compressed=compressed,vram=start,ram_end=end))
    if len(result)<16:return []
    return result


def unpack(image, row):
    """Expand one stored, zlib or bounded control-byte LZ member."""
    lo,hi=row['start'],row['end']
    if not 0<=lo<hi<=len(image):raise formats.AssetError('The archive member is out of bounds.')
    if not row['compressed']:
        if hi-lo>formats.MAX_BYTES:raise formats.AssetError('The archive member is too large to preview.')
        return bytes(image[lo:hi])
    header=struct.unpack_from('>I',image,lo)[0]
    length=header&0x7fffffff
    if length<4 or lo+length>hi:raise formats.AssetError('The archive member header is invalid.')
    if header>>31:
        try:
            stream=zlib.decompressobj()
            data=stream.decompress(image[lo+4:lo+length],formats.MAX_BYTES+1)
        except zlib.error as error:
            raise formats.AssetError('The archive zlib stream is damaged.') from error
        if not stream.eof or stream.unused_data or len(data)>formats.MAX_BYTES:
            raise formats.AssetError('The archive zlib stream is incomplete or too large.')
        return data
    if header>>28:raise formats.AssetError('This archive compression variant is not supported.')
    data=bytearray();pos=lo+4;end=lo+length
    while pos<end:
        control=image[pos];pos+=1
        if control<0x80:
            if pos>=end:raise formats.AssetError('The archive back-reference is incomplete.')
            distance=((control<<8)|image[pos])&0x3ff;pos+=1
            size=(control>>2)+2
            if not distance or distance>len(data):raise formats.AssetError('The archive back-reference is invalid.')
            if len(data)+size>formats.MAX_BYTES:raise formats.AssetError('The archive member is too large.')
            for _ in range(size):data.append(data[-distance])
        elif control<0xa0:
            size=control&0x1f
            if pos+size>end:raise formats.AssetError('The archive literal is incomplete.')
            data.extend(image[pos:pos+size]);pos+=size
        elif control<0xc0:
            return bytes(data)
        elif control<0xe0:
            if pos>=end:raise formats.AssetError('The archive repeat is incomplete.')
            size=(control&0x1f)+2;data.extend(bytes([image[pos]])*size);pos+=1
        elif control<0xff:
            size=(control&0x1f)+2;data.extend(bytes(size))
        else:
            if pos>=end:raise formats.AssetError('The archive zero run is incomplete.')
            size=image[pos]+2;pos+=1;data.extend(bytes(size))
        if len(data)>formats.MAX_BYTES:raise formats.AssetError('The archive member is too large.')
    return bytes(data)
