"""Runtime libmus previews use repeated, fully validated relocated controls."""
import base64
import io
import struct
import wave

import pytest

from decompassets import n64
from decompassets.n64 import runtime_ptr_audio

from .test_ptr_audio import fixture


def relocated(ram, image, at, *, different_book=False):
    control = bytearray(image[64:320])
    address = 0x80000000 + at
    struct.pack_into('>I', control, 16, 0x80000000)
    for offset in (36, 40, 44):
        value = struct.unpack_from('>I', control, offset)[0]
        struct.pack_into('>I', control, offset, address+value)
    for offset in (224, 228):
        value = struct.unpack_from('>I', control, offset)[0]
        struct.pack_into('>I', control, offset, address+value)
    for offset in (48, 112):
        value = struct.unpack_from('>I', control, offset)[0]
        struct.pack_into('>I', control, offset, 320+value)
        control[offset+9] = 1
        book = struct.unpack_from('>I', control, offset+16)[0]
        struct.pack_into('>I', control, offset+16, address+book)
    if different_book:
        struct.pack_into('>h', control, 80, 1)
    ram[at:at+len(control)] = control


def example():
    image = fixture()
    ram = bytearray(4096)
    relocated(ram, image, 1024)
    return image, ram


def test_repeated_relocated_controls_preview_cartridge_samples():
    image, ram = example()
    found = runtime_ptr_audio.regions(image, [bytes(ram), bytes(ram)])
    assert len(found) == 3 and len(found[0]['samples']) == 2
    assert found[0]['offset'] == 320
    preview = n64.preview(image, found[0], {'sample': 1})
    with wave.open(io.BytesIO(base64.b64decode(preview['data_url'].split(',')[1]))) as audio:
        assert audio.getframerate() == 22050 and any(audio.readframes(audio.getnframes()))
    with pytest.raises(n64.AssetError):
        n64.preview(image, found[0], {'sample': 2})


def test_invalid_or_nonrecurring_controls_do_not_create_assets():
    image, ram = example()
    assert not runtime_ptr_audio.regions(image, [bytes(ram)])
    changed = bytearray(ram)
    struct.pack_into('>I', changed, 1024+48, 336+16)
    assert not runtime_ptr_audio.regions(image, [bytes(ram), bytes(changed)])
    invalid = bytearray(image)
    invalid[336] = 0x0f
    assert not runtime_ptr_audio.regions(bytes(invalid), [bytes(ram), bytes(ram)])
    missing = bytearray(ram)
    struct.pack_into('>I', missing, 1024+48+16, 0x807ffffc)
    assert not runtime_ptr_audio.regions(image, [bytes(missing), bytes(missing)])


def test_different_control_graphs_for_one_wave_table_are_not_combined():
    image, ram = example()
    relocated(ram, image, 2048, different_book=True)
    assert not runtime_ptr_audio.regions(image, [bytes(ram), bytes(ram)])


def test_too_many_wave_markers_cannot_hide_a_later_boundary():
    from decompassets.n64 import ptr_audio

    image, ram = example()
    crowded = image + ptr_audio.WAVES * ptr_audio.MAX_BANKS
    assert not runtime_ptr_audio.regions(crowded, [bytes(ram), bytes(ram)])
