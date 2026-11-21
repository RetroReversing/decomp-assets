"""Read Borg12 DCM instrument tables and interleaved channel commands."""

import base64
import heapq
import struct
import sys
from array import array
from dataclasses import dataclass

from .. import formats
from . import borg, borg_audio, borg_dcm_render

_HEADER = struct.Struct('>8I')
_INSTRUMENT = struct.Struct('>4I')
_MAX_EVENTS = 262144


@dataclass(frozen=True, slots=True)
class Event:
    milliseconds: int
    channel: int
    pitch: int | None
    volume: int | None
    pan: int | None
    instrument: int | None
    sample_offset: int
    start: bool
    stop: bool


def decode(data, sample_sizes):
    if len(data) < _HEADER.size:
        return None
    ids, _, channels, count, size, loop, descriptors, stream = _HEADER.unpack_from(data)
    if (not 1 <= channels <= 64 or not 1 <= count <= 256 or not 0 <= loop < size
            or not _HEADER.size <= descriptors <= descriptors+count*16 <= stream <= stream+size <= ids
            or ids+count*4 > len(data)):
        return None
    instruments = []
    for i in range(count):
        index, = struct.unpack_from('>I', data, ids+i*4)
        _, start, end, flags = _INSTRUMENT.unpack_from(data, descriptors+i*16)
        frames = sample_sizes.get(index)
        if frames is None or not 0 <= start <= end <= frames:
            return None
        instruments.append((index, start, end, flags & 255))
    try:
        events = _events(data[stream:stream+size], channels, count)
    except (IndexError, ValueError):
        return None
    return instruments, events


def _events(data, channels, instruments):
    queue = [(0, channel) for channel in range(channels)]
    result = []
    at = milliseconds = prior = 0
    period = 20
    instrument_by_channel = [0]*channels

    def byte():
        nonlocal at
        value = data[at]
        at += 1
        return value

    while at < len(data):
        if len(result) >= _MAX_EVENTS:
            raise ValueError
        tick, channel = heapq.heappop(queue)
        milliseconds += (tick-prior)*period
        prior = tick
        command = byte()
        if command & 0x80:
            heapq.heappush(queue, (tick+2+(command & 127), channel))
            continue
        pitch = None
        if command & 0x40:
            value = byte() | byte()<<8
            shift = value>>14
            pitch = ((value & 0x3fff)<<shift)+(0, 0x4000, 0xc000, 0xc000)[shift]
        volume = byte() if command & 0x20 else None
        pan = byte() if command & 0x10 else None
        if command & 8:
            instrument_by_channel[channel] = byte()
        offset = byte()<<8 if command & 4 else 0
        stop = False
        if command & 1:
            control = byte()
            stop = bool(control & 0x80)
            if control & 0x40:
                tempo = byte()
                period = max(1, 2500//tempo) if tempo else 1
            if control & 0x20:
                byte()
        start = bool(command & 2)
        instrument = instrument_by_channel[channel] if start else None
        if instrument is not None and instrument >= instruments:
            raise ValueError
        result.append(Event(milliseconds, channel, pitch, volume, pan, instrument, offset, start, stop))
        heapq.heappush(queue, (tick+1, channel))
    return result



def regions(image, rows, samples, *, check=lambda: None, progress=lambda _: None):
    sizes = {asset['borg_index']:asset['samples'][0]['samples'] for asset in samples}
    result = []
    for index, (kind, compression, stored, expanded, offset) in enumerate(rows):
        if kind != 12:
            continue
        check()
        try:
            data = borg.member(image, offset, stored, expanded, compression)
        except formats.AssetError:
            continue
        score = decode(data, sizes)
        if score:
            instruments, events = score
            starts = sum(event.start for event in events)
            result.append(dict(offset=offset, size=stored, kind='music sequence', media='audio',
                               audio_kind='indexed sample directory',
                               samples=[dict(offset=offset, size=stored, codec='Borg DCM', preview_available=bool(starts))],
                               layout='borg-dcm', confidence='validated', label=f'Borg sequence {index}',
                               expanded_size=expanded, compression=compression, borg_index=index,
                               instruments=len(instruments), commands=len(events),
                               voice_starts=starts,
                               milliseconds=events[-1].milliseconds if events else 0,
                               reason='The instrument table links to bounded Borg PCM and the timed commands decode.',
                               preview_settings=dict(format='auto', source='rom', offset=offset)))
    return result


def preview(image, asset, selection):
    if 'sample' in selection:
        formats.integer(selection['sample'], 'Sequence', 0, 0)
        return _play(image, asset)
    return dict(media='metadata', title=asset['label'],
                fields={'Instruments':asset['instruments'], 'Channel commands':asset['commands'],
                        'Voice starts':asset['voice_starts'], 'Last command (ms)':asset['milliseconds']},
                settings=asset['preview_settings'])



def _play(image, asset):
    rows = borg.entries(image)
    index = asset['borg_index']
    if not 0 <= index < len(rows) or rows[index][0] != 12 or rows[index][4] != asset['offset']:
        raise formats.AssetError('The Borg sequence directory changed. Rescan ROM Explorer.')
    _, compression, stored, expanded, offset = rows[index]
    data = borg.member(image, offset, stored, expanded, compression)
    ids, _, _, count, *_ = _HEADER.unpack_from(data) if len(data) >= _HEADER.size else (0,)*8
    if not 1 <= count <= 256 or not _HEADER.size <= ids <= len(data)-4*count:
        raise formats.AssetError('The Borg instrument directory is invalid. Rescan ROM Explorer.')
    samples = {}
    decoded = 0
    for identifier in set(struct.unpack_from(f'>{count}I', data, ids)):
        if identifier >= len(rows) or rows[identifier][0] != 11:
            raise formats.AssetError('The sequence refers to an unknown Borg sample.')
        _, compression, stored, expanded, offset = rows[identifier]
        sample = borg.member(image, offset, stored, expanded, compression)
        info = borg_audio.sample(sample)
        if info is None:
            raise formats.AssetError('A Borg instrument sample exceeds its recorded extent.')
        begin, frames, width = info
        decoded += frames
        if decoded > 4*1024*1024:
            raise formats.AssetError('The Borg sequence exceeds the decoded sample limit.')
        if width == 1:
            pcm = array('h', ((value if value < 128 else value-256)*256 for value in sample[begin:begin+frames]))
        else:
            pcm = array('h')
            pcm.frombytes(sample[begin:begin+2*frames])
            if sys.byteorder == 'little':
                pcm.byteswap()
        samples[identifier] = pcm
    score = decode(data, {identifier:len(pcm) for identifier,pcm in samples.items()})
    if score is None:
        raise formats.AssetError('The Borg sequence commands changed. Rescan ROM Explorer.')
    instruments, events = score
    pcm, stats = borg_dcm_render.render(instruments, events, samples)
    payload, details = formats.pcm(pcm, dict(format='pcm-s16le', channels=2,
                                              rate=borg_dcm_render.RATE, length=len(pcm)))
    details.update(stats, format='Borg DCM', note='Single pass through the stored sequence with the original samples. Runtime mixing can differ.')
    return dict(media='audio', mime='audio/wav', details=details,
                data_url='data:audio/wav;base64,'+base64.b64encode(payload).decode(),
                settings={**asset['preview_settings'], 'sample':0})
