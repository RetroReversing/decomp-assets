import base64
import io
import struct
import wave

from decompassets import n64
from decompassets.n64 import sn64


def _fixture(*, truncate=False, bad_frame=False, samples_first=False):
    waves = bytes([15 if bad_frame else 0])+bytes([0x77])*8
    sample = struct.pack('>6I', 0, len(waves), 0, 0, 0xffffffff, 0)
    loops = struct.pack('>4H', 1, 0, 0, 1)
    book = struct.pack('>2I256s', 2, 1, bytes(256))
    body = bytes(4+20+(0 if samples_first else 8))+sample+loops+book
    bank = struct.pack('>4s8I6H2I', b'SN64',2,0,100,0,0,len(body),0,1,1,4,1,20,1,24,0,0)+body
    bank += bytes(-len(bank)%16)
    seq = struct.pack('>4s7I', b'SSEQ',2,0,1,0,0,16,0)
    entry = struct.pack('>HHIII', 1,0,20,0,0)
    seq += entry+bytes(20)
    seq += bytes(-len(seq)%16)
    if samples_first:
        samples = waves[:-1] if truncate else waves
        samples += bytes(-len(samples)%16)
        return bank+samples+seq
    return bank+seq+(waves[:-1] if truncate else waves)


def test_paired_sn64_sample_and_sequence_previews():
    image = _fixture()
    bank, sample, songs = sn64.regions(image)
    assert bank['samples'] == sample['samples']
    assert songs['sequences'][0]['tracks'] == 1
    assert n64.preview(image,songs,{})['media'] == 'metadata'
    result = n64.preview(image,bank,{'sample':0})
    raw = base64.b64decode(result['data_url'].split(',')[1])
    with wave.open(io.BytesIO(raw)) as wav:
        assert wav.getnframes() == 16
        assert any(wav.readframes(16))


def test_sn64_checks_sample_extents_and_predictor_selectors():
    assert not sn64.regions(_fixture(truncate=True))
    assert not sn64.regions(_fixture(bad_frame=True))


def test_sn64_accepts_a_sequence_directory_after_the_sample_table():
    image = _fixture(samples_first=True)
    bank, sample, songs = sn64.regions(image)
    assert bank['samples'] == sample['samples']
    assert songs['offset'] > sample['offset']
    assert songs['size'] > 0 and songs['sequences'][0]['tracks'] == 1
    result = n64.preview(image,bank,{'sample':0})
    with wave.open(io.BytesIO(base64.b64decode(result['data_url'].split(',')[1]))) as wav:
        assert any(wav.readframes(wav.getnframes()))
    assert not sn64.regions(_fixture(samples_first=True, bad_frame=True))
