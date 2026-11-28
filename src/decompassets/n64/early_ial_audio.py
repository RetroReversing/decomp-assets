"""Early EAD sound banks with paired ALSeqFile control and wave directories."""
import re
import struct

from . import ead_direct_audio, uso_audio

LAYOUT = 'early-ial-samples'
_HEADER = re.compile(rb'\x00\x01\x00[\x01-\x80]')
_MAX_BANKS = 128
_MAX_FRAME_CHECKS = 4*1024*1024


def _directory(image, at, revision, count):
    end = (4 + count*8 + 15) & ~15
    if at < 0 or at+end > len(image) or image[at:at+4] != struct.pack('>HH', revision, count):
        return None
    if any(image[at+4+count*8:at+end]):
        return None
    rows = [struct.unpack_from('>II', image, at+4+i*8) for i in range(count)]
    unique = sorted(set(rows))
    cursor = end
    for offset, size in unique:
        if offset != cursor or size < 16 or size % 16 or at+offset+size > len(image):
            return None
        cursor += size
    return rows, cursor


def _pointer(font, at):
    return int.from_bytes(font[at:at+4], 'big') if 0 <= at <= len(font)-4 else 0


def _voice(font, samples, wave, wave_offset, bank, index, found, budget, at):
    descriptor = _pointer(font, at)
    if not descriptor or descriptor % 4 or descriptor+20 > len(font):
        return
    flags, sample_offset, loop, book, length = struct.unpack_from('>5I', font, descriptor)
    if (flags or sample_offset % 16 or length < 9 or length % 9 not in (0, 1)
            or sample_offset+length > len(samples) or book % 4 or loop % 4
            or not 0 < book <= len(font)-8 or not 0 < loop <= len(font)-16):
        return
    order, predictors = struct.unpack_from('>2I', font, book)
    if order != 2 or not 1 <= predictors <= 8 or book+8+32*predictors > len(font):
        return
    first, last, repeat = struct.unpack_from('>3I', font, loop)
    if not 0 <= first < last <= (length//9+1)*16 or repeat not in (0, 0xffffffff):
        return
    sample = uso_audio._Sample(sample_offset, length, book+8, predictors)
    frames = sample.encoded_size//9
    if frames > budget[0]:
        return
    budget[0] -= frames
    if not uso_audio._fits(samples, 0, sample):
        return
    address = wave+wave_offset+sample_offset
    key = address, length, bank+16+book+8
    found[key] = dict(offset=address, size=length, encoded_size=sample.encoded_size,
                      rate=32000, samples=sample.encoded_size//9*16, codec='N64 VADPCM',
                      book_offset=bank+16+book+8, predictors=predictors, bank=index)


def _samples(image, control, wave, control_rows, wave_rows, check):
    found = {}
    budget = [_MAX_FRAME_CHECKS]
    for index, ((offset, size), (wave_offset, wave_size)) in enumerate(zip(control_rows, wave_rows)):
        check()
        bank = control+offset
        instruments, drums = struct.unpack_from('>2I', image, bank)
        if instruments > _MAX_BANKS or drums > _MAX_BANKS or 16+4+instruments*4 > size:
            return []
        font = image[bank+16:bank+size]
        samples = image[wave+wave_offset:wave+wave_offset+wave_size]

        for i in range(instruments):
            instrument = _pointer(font, 4+4*i)
            if instrument and instrument % 4 == 0 and instrument+32 <= len(font):
                for sound in (8, 16, 24):
                    _voice(font, samples, wave, wave_offset, bank, index, found, budget, instrument+sound)
        drum_table = _pointer(font, 0)
        if drum_table and drum_table % 4 == 0 and drum_table+drums*4 <= len(font):
            for i in range(drums):
                drum = _pointer(font, drum_table+4*i)
                if drum and drum % 4 == 0 and drum+16 <= len(font):
                    _voice(font, samples, wave, wave_offset, bank, index, found, budget, drum+4)
    return sorted(found.values(), key=lambda item: (item['offset'], item['book_offset']))


def regions(image, *, check=lambda: None, **kwargs):
    result = []
    for number, match in enumerate(_HEADER.finditer(image)):
        if number % 256 == 0:
            check()
        start = match.start()
        if start % 16:
            continue
        count = image[start+3]
        control = _directory(image, start, 1, count)
        if control is None:
            continue
        controls, extent = control
        candidates = []
        for padding in range(0, 257, 16):
            wave = start+extent+padding
            if any(image[start+extent:wave]):
                break
            if (waves := _directory(image, wave, 2, count)) is not None:
                candidates.append((wave, waves))
        if len(candidates) != 1:
            continue
        wave, waves = candidates[0]
        samples = _samples(image, start, wave, controls, waves[0], check)
        if len(samples) < 3:
            continue
        for index, sample in enumerate(samples, 1):
            sample['label'] = f'Sample {index}'
        result.append(dict(offset=start, size=wave-start, kind='audio', media='audio', layout=LAYOUT,
                           audio_kind='sample bank', label=f'Early EAD sample bank ({len(samples)} samples)',
                           confidence='validated', samples=samples, rate_basis='Preview rate',
                           reason='Paired bounded control and wave directories, instrument pointers, loops, '
                                  'predictor books and every ADPCM frame selector agree. Preview rate is adjustable.',
                           preview_settings=dict(format='auto', source='rom', offset=start)))
    return result


preview = ead_direct_audio.preview
