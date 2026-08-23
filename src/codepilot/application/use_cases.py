from __future__ import annotations

from codepilot.domain.models import Failure, Problem, Screenshot, Solution
from codepilot.services.ports import AIService, InputService
from codepilot.application.session_service import SessionService


class CaptureScreenshot:
    def __init__(self, session: SessionService, input_service: InputService) -> None:
        self.session = session
        self.input = input_service

    def execute(self) -> Screenshot:
        data, mime = self.input.capture()
        screenshot = Screenshot(data, mime)
        self.session.add_screenshot(screenshot)
        return screenshot


class AnalyzeAndSolve:
    def __init__(self, session: SessionService, ai: AIService, input_service: InputService) -> None:
        self.session = session
        self.ai = ai
        self.input = input_service

    def execute(self, preference: str, generation: int) -> None:
        model = self.ai.get_model(preference)
        screenshots = [(x.data, x.mime) for x in self.session.state.screenshots]
        if not screenshots:
            screenshots = [self.input.capture()]

        current = self.ai.inspect_problem(screenshots, model)
        if not self.session.generations.is_current(generation):
            return

        self.session.state.problem = Problem(current)
        if not current.get("coding_page_visible"):
            self.session.clear_screenshots()
            return

        if str(current.get("problem_type", "CODE")).upper() == "MCQ":
            answer = current.get("mcq_correct_answer", "?")
            self.session.state.solution = Solution(f"Answer: {answer}")
        else:
            code = self.ai.solve(current, self.session.state.previous_code, self.session.state.failure, model)
            if not self.session.generations.is_current(generation):
                return
            self.session.state.solution = Solution(code)

        self.session.state.active_model = preference
        self.session.clear_screenshots()


class AnalyzeResult:
    def __init__(self, session: SessionService, ai: AIService, input_service: InputService) -> None:
        self.session = session
        self.ai = ai
        self.input = input_service

    def execute(self) -> dict:
        image, mime = self.input.capture()
        result = self.ai.inspect_result(image, mime)
        status = str(result.get("status", "UNKNOWN")).upper()
        if status == "ACCEPTED":
            self.session.reset()
        elif status not in {"RUNNING", "NO_RESULT", "UNKNOWN"}:
            self.session.state.failure = Failure(result)
            self.session.state.previous_code = self.session.state.solution.code if self.session.state.solution else None
        return result
