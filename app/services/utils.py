"""공통 유틸리티 — LLM API 비용 통합 기록"""

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)


async def log_llm_cost(
    response,  # LLMResponse 객체
    action: str,
    project_id: str = '',
) -> float:
    """통합 LLM 응답의 비용을 DB에 기록합니다.

    response: LLMResponse from llm_client
    Returns: 기록된 비용 (USD)
    """
    from app.services.cost_service import CostTracker

    if response is None:
        return 0.0

    try:
        tracker = CostTracker()
        await tracker.log_cost(
            service=response.provider,      # 'claude' or 'gemini'
            action=action,
            units=response.input_tokens + response.output_tokens,
            cost_usd=response.cost_usd,
            project_id=project_id,
        )
    except Exception as e:
        logger.error(f'Failed to log cost: {e}')

    return response.cost_usd


# 하위 호환용 별칭 (기존 코드에서 import하는 경우)
async def log_claude_cost(
    response: Any,
    action: str,
    project_id: str = '',
    model: str = 'claude-haiku-4-5',
) -> float:
    """레거시 호환 — 기존 Claude 직접 호출 응답을 처리합니다."""
    from app.services.cost_service import CostTracker

    PRICE = {
        'claude-haiku-4-5': (1.0, 5.0),
        'claude-sonnet-4-5': (3.0, 15.0),
    }
    input_price, output_price = PRICE.get(model, (1.0, 5.0))

    usage = getattr(response, 'usage', None)
    if usage is None and isinstance(response, dict):
        usage = response.get('usage')
    if usage is None:
        return 0.0

    input_tokens = int(getattr(usage, 'input_tokens', 0))
    output_tokens = int(getattr(usage, 'output_tokens', 0))
    if isinstance(usage, dict):
        input_tokens = int(usage.get('input_tokens', input_tokens))
        output_tokens = int(usage.get('output_tokens', output_tokens))

    cost_usd = (input_tokens * input_price / 1_000_000) + (output_tokens * output_price / 1_000_000)

    try:
        tracker = CostTracker()
        await tracker.log_cost(
            service='claude', action=action,
            units=input_tokens + output_tokens,
            cost_usd=cost_usd, project_id=project_id,
        )
    except Exception as e:
        logger.error(f'Failed to log cost: {e}')

    return cost_usd