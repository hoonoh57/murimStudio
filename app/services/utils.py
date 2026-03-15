"""공통 유틸리티 — Claude API 비용 기록 등"""

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)


async def log_claude_cost(
    response: Any,
    action: str,
    project_id: str = '',
    model: str = 'claude-haiku-4-5',
) -> float:
    """Claude API 응답에서 토큰 사용량을 추출하고 DB에 비용을 기록합니다.

    Returns:
        기록된 비용 (USD)
    """
    from app.services.cost_service import CostTracker

    # Haiku 4.5 가격: input $1/M, output $5/M
    PRICE = {
        'claude-haiku-4-5': (1.0, 5.0),
        'claude-sonnet-4-5': (3.0, 15.0),
        'claude-opus-4-5': (5.0, 25.0),
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

    cost_usd = (input_tokens * input_price / 1_000_000) + \
               (output_tokens * output_price / 1_000_000)

    try:
        tracker = CostTracker()
        await tracker.log_cost(
            service='claude',
            action=action,
            units=input_tokens + output_tokens,
            cost_usd=cost_usd,
            project_id=project_id,
        )
    except Exception as e:
        logger.error(f'Failed to log cost: {e}')

    return cost_usd
