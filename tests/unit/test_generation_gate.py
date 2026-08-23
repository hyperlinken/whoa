from codepilot.infrastructure.lifecycle import GenerationGate


def test_stale_generation_is_rejected():
    gate = GenerationGate()
    first = gate.new()
    second = gate.new()
    assert not gate.is_current(first)
    assert gate.is_current(second)
