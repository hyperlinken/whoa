from codepilot.application.session_service import SessionService
from codepilot.domain.models import Screenshot


def test_reset_invalidates_state():
    session = SessionService()
    session.add_screenshot(Screenshot(b"x", "image/png"))
    generation = session.next_generation()
    session.reset()
    assert not session.state.screenshots
    assert session.state.problem is None
    assert session.state.solution is None
    assert session.state.generation != generation
