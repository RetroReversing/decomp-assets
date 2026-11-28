"""Early sound directories require matching graph and sample bounds."""
import base64
import io
import struct
import wave

from decompassets import n64
from decompassets.n64 import early_ial_audio


def fixture():
    data = bytearray(0x1c0)
    control, wave = 0x20, 0x180
    struct.pack_into('>HHII', data, control, 1, 1, 0x10, 0x130)
    struct.pack_into('>HHII', data, wave, 2, 1, 0x10, 0x30)
    bank = control+0x10
    struct.pack_into('>2I', data, bank, 3, 0)
    font = bank+16
    struct.pack_into('>4I', data, font, 0, 0x20, 0x40, 0x60)
    for index in range(3):
        instrument = font+0x20+index*0x20
        descriptor = 0x80+index*0x14
        struct.pack_into('>I', data, instrument+16, descriptor)
        struct.pack_into('>5I', data, font+descriptor, 0, index*16, 0xe8, 0xc0, 9)
        data[wave+0x10+index*16:wave+0x10+index*16+9] = bytes([0, 0x11, 0x11, 0x11, 0x11, 0x11, 0x11, 0x11, 0x11])
    struct.pack_into('>2I', data, font+0xc0, 2, 1)
    struct.pack_into('>3I', data, font+0xe8, 0, 16, 0)
    return data


def test_paired_directories_validate_samples_and_preview():
    data = fixture()
    assets = early_ial_audio.regions(data)
    assert len(assets) == 1 and len(assets[0]['samples']) == 3
    preview = n64.preview(data, assets[0], {'sample': 1})
    assert preview['mime'] == 'audio/wav'
    with wave.open(io.BytesIO(base64.b64decode(preview['data_url'].split(',', 1)[1]))) as decoded:
        assert any(decoded.readframes(decoded.getnframes()))
    assert n64.preview(data, assets[0], {'rate': 22050})['details']['rate'] == 22050


def test_corruption_and_ambiguous_padding_are_not_audio():
    data = fixture()
    data[0x20+0x140] = 1  # The gap between control and wave must be padding.
    assert not early_ial_audio.regions(data)
    data = fixture()
    data[0x190] = 1  # Predictor 1 is invalid for this one-predictor book.
    assert not early_ial_audio.regions(data)
    data = fixture()
    struct.pack_into('>I', data, 0x20+0x10+16+4, 0xfffffff0)
    assert not early_ial_audio.regions(data)
    assert not early_ial_audio.regions(fixture()[:-8])
