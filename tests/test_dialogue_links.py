import struct

from decompassets import n64
from decompassets.n64 import dialogue_links as links

from .test_dialogue import _resource
from .test_rnc_textures import sum_block


def archive(records):
    directory = bytearray()
    content = bytearray()
    for data, record in records:
        directory.extend(struct.pack('>III', 12 * len(records) + len(content), len(data), sum(data)))
        content.extend(record)
    return bytes(directory + content)


def test_dialogue_links_follow_keys_through_verified_audio_and_cutscene_directories():
    cue_ids = [f'S00000{i}A' for i in range(5)]
    script = b'KEY:\tA=\tGuide\n<INTRO>\n' + b''.join(
        cue.encode() + b'\tSample text\n' for cue in cue_ids
    ) + b'<END>\n'
    commands = b'NCS\0' + struct.pack('>iIII', 0, 0, 1, 3)
    packed_commands = sum_block(commands)
    packed_commands += bytes(-len(packed_commands) % 4) + b'END!'
    dialogue_directory = archive([(script, _resource(script))] + [(commands, packed_commands)] * 4)

    metadata = b'FFIR\0\0\0\0EVAW'
    compressed = sum_block(metadata)
    packed = compressed + bytes(-len(compressed) % 4) + b'END!'
    speech_directory = archive([(metadata, packed)] * 5)
    stream = struct.pack('>III', 11025, 1, 4) + b'\1\2\3\4'
    audio_directory = archive([(stream, _resource(stream))] * 4)

    speech_table = b''.join(
        links.KEY_ROW.pack(links._filename_key(b'audio\\speech\\english\\level00\\scene00\\' +
                                               cue[1:].lower().encode() + b'.wav'), i, 0)
        for i, cue in enumerate(cue_ids)
    ) + links.SPEECH_END + b''.join(links.VOICE_ROW.pack(i, i) for i in range(4))
    prefix = b'cutscene\\scripts\\english\\example\\take'
    cutscene_table = b''.join(
        links.KEY_ROW.pack(links._filename_key(prefix + f'{i:02}.ncs'.encode()), i, 0)
        for i in range(1, 5)
    ) + links.CUTSCENE_END + prefix + b'02.ncs\0'
    image = dialogue_directory + speech_directory + audio_directory + speech_table + cutscene_table
    assets = n64.regions(image)
    script_asset, = [asset for asset in assets if asset.get('layout') == 'dialogue-script']
    streams = [asset['offset'] for asset in assets if asset.get('audio_kind') == 'dean stream']
    rows = n64.preview(image, script_asset, {'dialogue_scene': 1})['table']['rows']
    assert [row.get('audio_offset') for row in rows] == [*streams, None]
    scripts = script_asset['cutscene_resources']
    assert [item['label'] for item in scripts] == [f'example/take{i:02}.ncs' for i in range(1, 5)]
    assert {item['offset'] for item in scripts} == {
        asset['offset'] for asset in assets if asset['label'] == 'NCS cutscene commands'
    }

    # An invalid FFIR checksum must prevent crossing from the filename table into audio.
    damaged = bytearray(image)
    damaged[len(dialogue_directory) + 5 * 12 + 15] ^= 1
    script_asset, = [a for a in n64.regions(bytes(damaged)) if a.get('layout') == 'dialogue-script']
    assert 'cue_audio' not in script_asset
    assert len(script_asset['cutscene_resources']) == 4
