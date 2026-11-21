import struct

from decompassets.n64 import borg_dcm


def _sequence(stream, *, end=16, channels=2):
    ids = 48+len(stream)
    header = struct.pack('>8I', ids, 0, channels, 1, len(stream), 0, 32, 48)
    instrument = struct.pack('>4I', 0, 0, end, 255)
    return header+instrument+stream+struct.pack('>I', 20)


def test_dcm_interleaves_channels_and_preserves_waits():
    # Channel zero starts, channel one waits two ticks. Channel zero
    # changes the tempo at tick one, then channel one starts at tick two.
    data = _sequence(bytes.fromhex('4a 10 40 00 80 01 40 fa 80 02'))
    instruments, events = borg_dcm.decode(data, {20: 16})
    assert instruments == [(20, 0, 16, 255)]
    assert [(e.milliseconds, e.channel, e.start) for e in events] == [
        (0, 0, True), (20, 0, False), (30, 1, True)]
    assert events[0].pitch == 16416


def test_dcm_checks_sample_links_loops_and_command_bounds():
    assert borg_dcm.decode(_sequence(bytes.fromhex('02')), {20: 15}) is None
    assert borg_dcm.decode(_sequence(bytes.fromhex('0a 01')), {20: 16}) is None
    assert borg_dcm.decode(_sequence(bytes.fromhex('42 00')), {20: 16}) is None
