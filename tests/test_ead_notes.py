from decompassets.n64 import ead_notes


def test_channel_program_is_retained_across_timed_layer_launches():
    root = bytes.fromhex('90000cfd02900011fd187fff')
    configure = bytes.fromhex('c105dd20ff')
    channel = bytes.fromhex('c4880017fd18')
    layer = bytes.fromhex('0c106040ff')
    score = ead_notes.notes(root + configure + channel + layer)
    assert score['notes'] == [ead_notes.Note(2, 12, 0, 0, 12, 96, 5, None, 127, 32)]
    assert score['incomplete'] == 0
    assert ead_notes.notes(root + configure + channel)['incomplete'] == 1


def test_layer_calls_and_loops_share_a_bounded_tick_window():
    root = bytes.fromhex('900006fd30ff')
    channel = bytes.fromhex('c488000dff0000')
    layer = bytes.fromhex('f802fc001af7ff000000000000')
    phrase = bytes.fromhex('46087fff')
    score = ead_notes.notes(root + channel + layer + phrase, tick_limit=12)
    assert [(n.tick,n.duration,n.key) for n in score['notes']] == [(0,8,6),(8,4,6)]
    assert score['incomplete'] == 0
