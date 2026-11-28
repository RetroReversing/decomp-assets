import base64
import io
import wave

from decompassets.n64 import bnkb_audio


def fixture():
    data = bytearray(256)
    data[:12] = b'BNKb\x02\0\0\x01\0\0\0\x80'
    data[12:16] = (4).to_bytes(4, 'big')
    record = (b'PT\x02\0\x85\x02\0\x10\x84\x02\x3e\x80'
              b'\x88\x04\0\0\0\x80\x8f\x88\0\0\0\x02\0\0\0\x01' + bytes(32))
    data[16:16+len(record)] = record
    data[128:137] = b'\0\x12\x34\x56\x78\x9a\xbc\xde\xf0'
    return data


def test_sample_preview_and_invalid_pointers():
    data = fixture()
    bank, = bnkb_audio.regions(data)
    assert len(bank['samples']) == 1
    result = bnkb_audio.preview(data, bank, {})
    with wave.open(io.BytesIO(base64.b64decode(result['data_url'].split(',')[1]))) as output:
        assert output.getframerate() == 16000
        assert output.getnframes() == 16
        assert any(output.readframes(16))
    data[12:16] = (0x1000).to_bytes(4, 'big')
    assert bnkb_audio.regions(data) == []


def test_rejects_frame_with_unknown_predictor():
    data = fixture()
    data[128] = 1
    assert bnkb_audio.regions(data) == []


def pcm_fixture():
    """A version-four bank with one 28-sample EA-XA frame."""
    data = bytearray(0x40 + 15)
    data[:20] = b'BNKb\x04\0\0\x01\0\0\0\x40\0\0\0\x0f\0\0\0\0'
    data[20:24] = (4).to_bytes(4, 'big')
    record = (b'PT\x02\0\xfd\x85\x02\0\x1c\x84\x02\x3e\x80'
              b'\x83\x01\x07\x88\x04\0\0\0\x40\xff')
    data[24:24+len(record)] = record
    data[0x40:] = b'\x0c' + b'\x1f' * 14
    return data


def test_ea_xa_sample_preview_and_bank_bounds():
    data = pcm_fixture()
    bank, = bnkb_audio.regions(data)
    assert bank['samples'][0]['codec'] == 'EA-XA'
    result = bnkb_audio.preview(data, bank, {})
    with wave.open(io.BytesIO(base64.b64decode(result['data_url'].split(',')[1]))) as output:
        assert output.getframerate() == 16000 and output.getnframes() == 28
        assert output.readframes(2) == b'\x01\0\xff\xff'
    data[15] = 14
    assert not bnkb_audio.regions(data)


def test_ea_xa_missing_rate_is_identified_as_default():
    data = pcm_fixture()
    pos = data.find(b'\x84\x02\x3e\x80')
    data[pos:pos+4] = b'\xfc' * 4
    bank, = bnkb_audio.regions(data)
    assert bank['samples'][0]['rate'] == 22050
    assert bank['samples'][0]['rate_inferred']
    assert 'defaults' in bank['reason']
