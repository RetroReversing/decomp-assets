"""A compressed control bank needs a uniquely verified wave table."""
import base64
import io
import struct
import wave

from decompassets import n64
from decompassets.n64 import audio, rnc_control_audio

from .test_rnc import literal_block


def cartridge(count=64):
    sounds = 336
    envelope = sounds+16*count
    keymap = envelope+16
    waves = keymap+8
    book = waves+20*count
    ctl = bytearray(book+64)
    ctl[:8] = b'B1'+struct.pack('>HI', 1, 32)
    struct.pack_into('>HBBIII', ctl, 32, 1, 0, 0, 22050, 0, 64)
    struct.pack_into('>BBBB', ctl, 64, 127, 64, 0, 0)
    struct.pack_into('>H', ctl, 78, count)
    struct.pack_into('>iiiBBxx', ctl, envelope, 0, -1, 16666, 127, 127)
    ctl[keymap:keymap+6] = bytes([0, 127, 0, 127, 60, 0])
    struct.pack_into('>II16h', ctl, book, 2, 1, *([0]*16))
    struct.pack_into('>II8h', ctl, book+40, 1, 1, *([0]*8))
    sample = (bytes([0])+bytes([0x11])*8)*2
    for i in range(count):
        sound, table = sounds+i*16, waves+i*20
        struct.pack_into('>I', ctl, 80+i*4, sound)
        struct.pack_into('>IIIBBBx', ctl, sound, envelope, keymap, table, 64, 127, 0)
        struct.pack_into('>IIBBxxII', ctl, table, i*24, 18, 0, 0, 0, book+40 if i == count-1 else book)
    packed = literal_block(bytes(ctl))
    prefix = packed+bytes((-len(packed)) % 8)
    wave_table = (sample+bytes(6))*(count-1)+sample
    return prefix+wave_table, len(prefix)


def test_compressed_control_finds_and_previews_only_supported_samples():
    image, base = cartridge()
    asset, = rnc_control_audio.regions(image)
    assert asset['table_offset'] == base
    assert len(asset['samples']) == 63 and asset['unsupported_samples'] == 1
    result = n64.preview(image, asset, {'sample': 0})
    raw = base64.b64decode(result['data_url'].split(',')[1])
    with wave.open(io.BytesIO(raw)) as wav:
        assert wav.getframerate() == 22050
        assert any(wav.readframes(wav.getnframes()))


def test_ambiguous_or_corrupted_wave_table_is_not_recognized():
    image, base = cartridge()
    assert not rnc_control_audio.regions(image+bytes(6)+image[base:])
    broken = bytearray(image)
    broken[base+18] = 1
    assert not rnc_control_audio.regions(broken)
    assert not rnc_control_audio.regions(image[:20])


def test_partial_banks_cannot_be_used_as_programs():
    image, _ = cartridge()
    from decompassets import rnc
    ctl, _ = rnc.unpack_at(image, 0)
    try:
        audio.bank(ctl, 0, partial_samples=True)
    except audio.BankError as error:
        assert 'only as samples' in str(error)
    else:
        raise AssertionError('Partial sample banks must not expose incomplete programs')


def test_invalid_sample_frames_are_excluded_from_an_otherwise_verified_bank():
    image, base = cartridge()
    broken = bytearray(image)
    broken[base] = 1  # Predictor 1 is outside this sample's one-entry book.
    asset, = rnc_control_audio.regions(broken)
    assert len(asset['samples']) == 62 and asset['unsupported_samples'] == 2
    assert all(sample['offset'] != base for sample in asset['samples'])


def test_smaller_bank_needs_at_least_32_verified_samples():
    image, _ = cartridge(count=33)
    asset, = rnc_control_audio.regions(image)
    assert len(asset['samples']) == 32 and asset['unsupported_samples'] == 1
