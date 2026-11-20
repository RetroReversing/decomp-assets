import struct

import pytest

from decompassets import n64
from decompassets.formats import AssetError
from decompassets.n64 import dialogue


def _resource(data):
    return b'RAW!' + struct.pack('>I', len(data)) + data + b'!' * (-len(data) % 4) + b'END!'


def _archive():
    english = (b'KEY:\tA=\tGuide\r\n\tB=\tTraveller\r\n'
               b'<INTRO>\tArrival\r\nS000000A\tWelcome.\r\nS000001B\tHello.\r\n'
               b'<SECOND>\r\n' +
               b''.join(f'S01{i:04d}A\tCue {i}.\r\n'.encode() for i in range(70)) +
               b'<END>\r\n')
    german = (b'SCHL\xdcSSEL:\tA=\tF\xfchrer\r\n<BESUCH>\r\n'
              b'S000000A\tGr\xfc\xdfe.\r\n<END>\r\n')
    directory = bytearray()
    resource = bytearray()
    for data in (english, german):
        directory.extend(struct.pack('>III', 24 + len(resource), len(data), sum(data)))
        resource.extend(_resource(data))
    return bytes(directory + resource)


def test_dialogue_regions_page_and_filter_exact_cues():
    image = _archive()
    english, german = [asset for asset in n64.regions(image) if asset.get('layout') == 'dialogue-script']
    assert english['dialogue']['scenes'][0] == dict(name='INTRO', caption='Arrival', lines=2)
    assert english['dialogue']['speakers'] == {'A': 'Guide', 'B': 'Traveller'}
    first = n64.preview(image, english, {})['table']
    assert first['total'] == 72 and len(first['rows']) == 64
    second = n64.preview(image, english, {'dialogue_scene': 2, 'record_page': 1})['table']
    assert second['total'] == 70 and second['rows'][0]['cue_id'] == 'S010064A'
    speaker = n64.preview(image, english, {'dialogue_speaker': 'B'})['table']
    assert [(row['speaker'], row['text']) for row in speaker['rows']] == [('Traveller', 'Hello.')]
    translated = n64.preview(image, german, {})['table']['rows'][0]
    assert translated['speaker'] == 'Führer' and translated['text'] == 'Grüße.'
    with pytest.raises(AssetError, match='speaker'):
        n64.preview(image, german, {'dialogue_speaker': 'X'})


def test_tables_require_a_checksum_match_and_a_script_terminator():
    image = bytearray(_archive())
    image[11] ^= 1
    assets = dialogue.regions(image)
    assert [asset['dialogue']['language'] for asset in assets] == ['German']
    assert not dialogue.regions(_resource(b'KEY:\tA=\tGuide\r\n<SCENE>\r\nS000000A\tMissing terminator.'))
