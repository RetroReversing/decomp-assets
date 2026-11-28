"""Relocated sound controls require agreeing RAM observations and valid sample frames."""
import struct

from decompassets.n64 import audio, runtime_audio

from .test_native_audio import fixture


def observed():
    image, _, table = fixture()
    image = bytearray(image)
    struct.pack_into('>16h', image, 128+328, *range(16))
    ram = bytearray(4096)
    start = 1024
    ram[start:start+512] = image[128:128+512]
    for at, relative in ((256, 0), (280, 40)):
        struct.pack_into('>I', ram, start+at, table+relative)
        ram[start+at+9] = 1
    return bytes(image), bytes(ram), table


def test_runtime_control_relocations_prove_sample_table():
    image, ram, table = observed()
    found = runtime_audio.regions(image, [ram, ram])
    assert len(found) == 3
    assert found[0]['table_offset'] == table
    assert found[0]['table_confidence'] == 'runtime relocated controls'
    assert [sample['label'] for sample in found[0]['samples']] == ['Sample 1', 'Sample 2']
    assert found[1]['samples'][0]['label'] == 'Sample 1'
    assert audio.preview(image, found[0], {})['media'] == 'audio'


def test_runtime_evidence_must_agree_and_samples_must_be_valid():
    image, ram, table = observed()
    assert not runtime_audio.regions(image, [ram])
    conflicting = bytearray(ram)
    struct.pack_into('>I', conflicting, 1024+280, table+48)
    assert not runtime_audio.regions(image, [ram, bytes(conflicting)])
    invalid = bytearray(image)
    invalid[table] = 0x0f
    assert not runtime_audio.regions(bytes(invalid), [ram, ram])
