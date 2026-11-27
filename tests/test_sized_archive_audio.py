"""Sized-file directory and relocated audio controls, built from synthetic data."""
import struct

from decompassets.n64 import audio, sized_archive_audio

from .test_dean_codec import _image
from .test_native_audio import fixture, wav


def _control(data, relocation):
    data = bytearray(data)
    for field in (4, 44, 80, 84, 128, 132, 136, 144, 148, 152, 272, 296):
        value, = struct.unpack_from('>I', data, field)
        struct.pack_into('>I', data, field, relocation + value)
    for flag in (34, 67, 142, 158, 265, 289):
        data[flag] = 1
    return data


def _archive():
    image, _, table = fixture()
    bank = image[128:table]
    first = 0x800014
    second = first + len(bank)
    control = struct.pack('>5I', 2, first, 0, second, 0) + _control(bank, first) + _control(bank, second)
    files = [(b'first.dat', b'1234'), (b'second.dat', b'5678'),
             (b'~audio~\\Music.tbl', image[table:]), (b'~audio~\\Music.ctl', control)]
    header = b''.join(struct.pack('>I', len(data)) + name + b'\0' for name, data in files)
    return header + b'\xff' * 4 + b''.join(data for _, data in files)


def test_archive_audio_requires_directory_controls_and_sample_frames():
    image = _archive()
    banks = sized_archive_audio.regions(image)
    assert len(banks) == 2 and all(len(bank['samples']) == 2 for bank in banks)
    rate, samples = wav(audio.preview(image, banks[1], {'sample': 1}))
    assert rate == 22050 and any(samples)
    broken = bytearray(image)
    broken[banks[1]['samples'][1]['offset']] = 0x0f  # invalid predictor selector
    assert not sized_archive_audio.regions(broken)
    assert not sized_archive_audio.regions(image[:-1])


def test_archive_dean_uses_exact_payload_size_from_its_marker():
    image, _, table = fixture()
    bank = bytearray(image[128:table])
    payload = bytes(12) + b'\x80\0' + bytes(4)
    struct.pack_into('>I', bank, 260, len(payload) - 2)
    struct.pack_into('>II4sIII', bank, 320, 1, 1, b'DEAN', 256, 2, len(payload))
    waves = bytearray(image[table:])
    waves[:len(payload)] = payload
    first = 0x800014
    second = first + len(bank)
    controls = struct.pack('>5I', 2, first, 0, second, 0) + _control(bank, first) + _control(bank, second)
    files = [(b'first.dat', b'1234'), (b'books.bin', _image(padding=8)),
             (b'~audio~\\Music.tbl', waves), (b'~audio~\\Music.ctl', controls)]
    header = b''.join(struct.pack('>I', len(data)) + name + b'\0' for name, data in files)
    archive = header + b'\xff' * 4 + b''.join(data for _, data in files)
    banks = sized_archive_audio.regions(archive)
    assert len(banks) == 2
    sample = banks[0]['samples'][0]
    assert sample['codec'] == 'Acclaim DEAN' and sample['size'] == len(payload)
    rate, samples = wav(audio.preview(archive, banks[0], {'sample': 0}))
    assert rate == 22050 and any(samples)
    damaged = bytearray(archive)
    marker = damaged.find(b'DEAN', banks[0]['offset'], banks[0]['offset'] + banks[0]['size'])
    damaged[marker:marker + 4] = b'FAKE'
    assert not any(bank['offset'] == banks[0]['offset'] and
                   any(sample['codec'] == 'Acclaim DEAN' for sample in bank['samples'])
                   for bank in sized_archive_audio.regions(damaged))
