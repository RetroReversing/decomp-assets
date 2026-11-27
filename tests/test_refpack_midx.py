import base64
import io
import wave

import pytest

from decompassets import formats
from decompassets.n64 import refpack_midx

from .test_shpn_images import literal


def score():
    # Note on, one beat, note off, end. One tick is 1/480 quarter note.
    return b'MIDx\0\x90\x45\x60\x7f\xff\xf8\x7f\xff\xf8\x7f\xff\xf8\x63\x80\x45\x40\0\xf0\x2f\0\0'


def test_complete_sequence_has_audible_explicitly_synthetic_preview():
    image = literal(score())
    asset, = refpack_midx.regions(image)
    assert asset['notes'] == 1
    result = refpack_midx.preview(image, asset, {})
    assert 'Synthetic' in result['details']['note']
    audio = base64.b64decode(result['data_url'].split(',')[1])
    with wave.open(io.BytesIO(audio)) as wav:
        assert wav.getframerate() == 16000
        assert any(wav.readframes(wav.getnframes()))


@pytest.mark.parametrize('data', [b'MIDx\0\x90\x45', b'MIDx\0\x90\xff\x40\0\xf0\x2f',
                                  b'MIDx\0\x90\x45\x40', score()+b'\x01'])
def test_truncated_or_invalid_sequence_is_not_an_asset(data):
    assert not refpack_midx.regions(literal(data))


def test_preview_revalidates_the_stream():
    image = literal(score())
    asset, = refpack_midx.regions(image)
    with pytest.raises(formats.AssetError):
        refpack_midx.preview(image[:-3], asset, {})


def test_raw_adjacent_sequences_preview_and_stop_at_their_own_end():
    data = b'prefix' + score() + b'padding' + score() + b'after'
    rows = [row for row in refpack_midx.regions(data) if row['layout'] == refpack_midx.RAW_LAYOUT]
    assert len(rows) == 2
    for row in rows:
        result = refpack_midx.preview(data, row, {})
        assert 'Synthetic' in result['details']['note']
        with wave.open(io.BytesIO(base64.b64decode(result['data_url'].split(',')[1]))) as audio:
            assert any(audio.readframes(audio.getnframes()))
    with pytest.raises(formats.AssetError):
        refpack_midx.preview(data[:rows[0]['offset']+rows[0]['size']-1], rows[0], {})


def test_raw_signatures_with_incomplete_or_invalid_events_are_not_sequences():
    data = b'MIDx\0\x90\x45' + b'junk' + b'MIDx\0\x90\xff\x40\0\xf0\x2f'
    assert not refpack_midx.regions(data)
