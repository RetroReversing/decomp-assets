import struct

from decompassets.n64 import indexed_partial_audio

from .test_native_audio import fixture, wav


def archive():
    image, _, table = fixture()
    payload = image[128:]
    controls = table - 128
    header = bytearray(0x120)
    sections = [0] * 50 + [8] + [8 + len(payload)] * 17
    struct.pack_into('>I68I', header, 0, 67, *sections)
    return bytes(header) + struct.pack('>II', controls, len(payload)) + payload


def test_archive_pairs_controls_with_bounded_sample_table():
    image = archive()
    bank, *samples = indexed_partial_audio.regions(image)
    assert len(samples) == 2
    assert len(bank['samples']) == 2
    assert [sample['label'] for sample in bank['samples']] == ['Sample 1', 'Sample 2']
    assert bank['table_confidence'] == 'validated'
    from decompassets.n64 import audio
    rate, pcm = wav(audio.preview(image, bank, {}))
    assert rate == 22050 and any(pcm)


def test_archive_rejects_sample_table_outside_section():
    image = bytearray(archive())
    struct.pack_into('>I', image, 0x124, 0xffffffff)
    assert not indexed_partial_audio.regions(image)
