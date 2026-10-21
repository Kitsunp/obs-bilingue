from engine.core import CaptionState


def test_many_technical_continuations_keep_only_bounded_independent_fragments():
    state = CaptionState(9)
    first_epoch = None
    for index in range(1000):
        segment = state.begin(continuation=index > 0)
        text = f"A separately identified fragment {index}."
        state.partial(segment, text, True)
        if index == 0:
            first_epoch = state.translation_token(segment)
        assert len(state.rows) <= state.style["max_rows"]
        assert state.source == text
    rows = state.snapshot()["rows"]
    assert len({row["flow_group"] for row in rows}) == 1
    assert len({row["epoch"] for row in rows}) == 3
    assert not state.translated(1, "A separately identified fragment 0.",
                                {"es": "Una respuesta antigua."}, first_epoch)
