from app.core.config import Settings
from app.services.llm.base import ChatTurn, LLMBackend

__all__ = ["ChatTurn", "LLMBackend", "build_llm_backend"]


def build_llm_backend(settings: Settings) -> LLMBackend:
    provider = settings.resolved_llm_provider
    if provider == "anthropic":
        from app.services.llm.anthropic_backend import AnthropicBackend

        return AnthropicBackend(settings)
    if provider == "openai":
        from app.services.llm.openai_backend import OpenAICompatibleBackend

        return OpenAICompatibleBackend(settings)
    from app.services.llm.offline_backend import OfflineBackend

    return OfflineBackend()
