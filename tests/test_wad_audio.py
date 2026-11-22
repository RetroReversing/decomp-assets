import base64
import io
import struct
import wave

from decompassets.n64 import wad_audio

from .test_native_audio import fixture


def test_paired_archive_bank_preview():
    image, _, table_start = fixture()
    control, table = image[128:table_start], image[table_start:]
    name = lambda s: s.encode().ljust(20, b'\0')
    header = 8 + 32 + 2 * 36
    one = struct.pack('>20sIIII', name('MUSIC.CTL'), header, 10, len(control), len(control))
    two = struct.pack('>20sIIII', name('MUSIC.TBL'), header+len(control), 11, len(table), len(table))
    inner = struct.pack('>II', 1, 1) + struct.pack('>20sIII', name('BANK'), 40, 2, 0) + one + two + control + table
    top = 8 + 32 + 4 * 36
    row = struct.pack('>20sIIII', name('BANK.WAD'), top, 4, len(inner), len(inner))
    archive = struct.pack('>II', 1, 1) + struct.pack('>20sIII', name('ROOT'), 40, 4, 0) + row*4 + inner
    assets = wad_audio.regions(archive)
    assert len(assets) == 1
    assert len(assets[0]['samples']) == 2
    result = wad_audio.preview(archive, assets[0], {'sample': 0})
    stream = wave.open(io.BytesIO(base64.b64decode(result['data_url'].split(',')[1])))
    assert any(stream.readframes(stream.getnframes()))
    assert wad_audio.regions(archive[:-1]) == []
