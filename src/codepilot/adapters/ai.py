from codepilot.legacy.gemini import GeminiAgent


class GeminiService:
    """Anti-corruption layer around the existing Gemini implementation."""

    def __init__(self) -> None:
        self._client = GeminiAgent()

    def get_model(self, preference):
        return self._client.get_model_by_preference(preference)

    def model_name(self, model):
        return self._client._model_name(model)

    def inspect_problem(self, screenshots, model=None):
        return self._client.inspect_problem(screenshots, force_model=model)

    def solve(self, problem, previous_code=None, failure=None, model=None):
        return self._client.solve(problem, previous_code, failure, force_model=model)

    def inspect_result(self, image, mime, model=None):
        return self._client.inspect_result(image, mime, force_model=model)

    def close(self):
        self._client.close()
