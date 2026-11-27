import struct

import pytest

from decompassets import formats, rnc
from decompassets.n64 import rnc_shpn_images as banks

from .test_rnc import literal_block
from .test_shpn_images import fixture


class _Bits:
    def __init__(self):
        self.data = bytearray()
        self.position = 8
        self.index = 0

    def bit(self, bit):
        if self.position == 8:
            self.index = len(self.data)
            self.data.append(0)
            self.position = 0
        self.data[self.index] |= bit << (7-self.position)
        self.position += 1

    def byte(self, value):
        self.data.append(value)


def _method2(raw):
    w = _Bits()
    w.bit(0); w.bit(0)
    for byte in raw:
        w.bit(0); w.byte(byte)
    w.bit(1); w.bit(1); w.bit(1); w.bit(1); w.byte(0); w.bit(0)
    payload = bytes(w.data)
    return b'RNC\x02'+struct.pack('>IIHHBB',len(raw),len(payload),rnc.crc16(raw),rnc.crc16(payload),0,1)+payload


def _rgba():
    raw = bytearray(b'SHPN'+bytes(4)+(1).to_bytes(4,'big')+b'GIMX')
    raw.extend(b'pic1'+(24).to_bytes(4,'big'))
    raw.extend(b'\x68\0\0\0\0\x02\0\x02'+bytes(8)+bytes.fromhex('f80107c1003fffff'))
    raw[4:8] = len(raw).to_bytes(4,'big')
    return raw


@pytest.mark.parametrize('pack', [literal_block, _method2])
def test_rnc_banks_validate_and_preview_indexed_and_direct_images(pack):
    for raw in (fixture(),_rgba()):
        packed = pack(raw)
        bank, = banks.regions(packed)
        assert bank['frames'] == 1
        result = banks.preview(packed,bank,{})
        assert result['media'] == 'image'
        assert result['settings']['palette'] == 0
        changed = bytearray(packed); changed[-1] ^= 1
        assert not banks.regions(changed)
        with pytest.raises(formats.AssetError):
            banks.preview(changed,bank,{})


def test_direct_image_cannot_exceed_its_directory_bound():
    data = _rgba()
    data[28:30] = (100).to_bytes(2,'big')
    assert not banks.regions(_method2(data))
