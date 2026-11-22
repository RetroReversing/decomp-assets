import struct
import zlib

import pytest

from decompassets import formats
from decompassets.n64 import indexed_runtime_archive as archive


def cartridge():
    data=bytearray(0x2000)
    at=0x1000;count=16
    data[at:at+16]=archive.MAGIC
    ranges=at-4-count*8
    for i in range(count):
        start=0x1200+i*16
        struct.pack_into('>I',data,at+16+4*i,0x80000000|start)
        struct.pack_into('>II',data,ranges+8*i,0x80001000,0x80002000)
        payload=zlib.compress(bytes([i])*8)
        struct.pack_into('>I',data,start,0x80000000|4+len(payload))
        data[start+4:start+4+len(payload)]=payload
    struct.pack_into('>I',data,at+16+4*count,0x1200+count*16)
    return data


def test_directory_and_zlib_member_are_bounded():
    data=cartridge();rows=archive.members(data)
    assert len(rows)==16
    assert archive.unpack(data,rows[0])==bytes(8)
    struct.pack_into('>I',data,0x1000+16+12,1)
    assert archive.members(data)==[]


@pytest.mark.parametrize('payload,expected',[(b'\x83abc\xa0',b'abc'),(b'\xc1x\xe1\xa0',b'xxx\0\0\0'),
                                             (b'\x83abc\x04\x03\xa0',b'abcabc')])
def test_lz_literals_repeats_and_backreferences(payload,expected):
    data=struct.pack('>I',len(payload)+4)+payload
    assert archive.unpack(data,dict(start=0,end=len(data),compressed=True))==expected


def test_bad_lz_backreference_is_rejected():
    data=struct.pack('>I',6)+b'\x00\x01'
    with pytest.raises(formats.AssetError):archive.unpack(data,dict(start=0,end=len(data),compressed=True))
