from decompassets.n64 import ead_sequence


def test_root_tracks_tempo_calls_and_repeated_channel_starts():
    # Tempo 144, call a channel starter, delay 256 ticks, then repeat the start twice.
    data = bytes.fromhex('dd90fc0010fd8100f802fc0010f7ff00 920014ff ff')
    result = ead_sequence.schedule(data)
    assert result['tempos'] == [(0,120), (0,144)]
    assert result['channels'] == [
        ead_sequence.ChannelStart(0,2,20),
        ead_sequence.ChannelStart(256,2,20),
        ead_sequence.ChannelStart(256,2,20),
    ]
    assert result['ticks'] == 256 and not result['loops']
    assert ead_sequence.schedule(data[:-1]) is None


def test_root_reports_conditional_fallthrough_and_stops_at_loop():
    data = bytes.fromhex('80f301fe90000afb0000 ff')
    result = ead_sequence.schedule(data)
    assert result['channels'] == [ead_sequence.ChannelStart(1,0,10)]
    assert result['loops'] and result['conditional']
    assert ead_sequence.schedule(bytes.fromhex('fd80')) is None
