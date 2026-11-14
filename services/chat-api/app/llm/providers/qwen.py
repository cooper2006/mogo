from app.llm.providers.default_openai import DefaultOpenAIClient
from app.llm.providers.pools import PROVIDER_QWEN

class QwenClient(DefaultOpenAIClient):
    """
    Qwen specific overrides or specialized structure support if needed.
    For now, it behaves identically to DefaultOpenAIClient since Qwen 
    offers an OpenAI compatible API endpoint.
    """

    #: FR-24 / T082：Qwen 与 default-openai 是两个上游，必须各自独立池。
    POOL_PROVIDER = PROVIDER_QWEN
