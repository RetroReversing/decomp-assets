import struct

from decompassets.n64 import audio, b1_speech


def test_speech_is_only_exposed_with_bounded_matching_header(monkeypatch):
    image = bytearray(128)
    struct.pack_into('>4sHHI', image, 64, b'MORT', 1, 22050, 4)
    monkeypatch.setattr(audio, '_candidates', lambda _: [(0, False)])
    monkeypatch.setattr(audio, 'bank', lambda *a, **k: {})
    monkeypatch.setattr(audio, '_following_sample_directory', lambda *_: (32, 64, (0, 16)))
    rows = b1_speech.regions(image)
    assert rows[0]['samples'][0]['offset'] == 64
    image[75] = 5
    assert b1_speech.regions(image) == []
