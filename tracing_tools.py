from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Generic, TypeVar

from browser_use.tools.service import Tools
from browser_use.tools.registry.views import ActionModel
from browser_use.agent.views import ActionResult

Context = TypeVar("Context")

@dataclass
class ExecutedAction:
    name: str
    params: dict[str, Any]
    start_s: float
    end_s: float
    result: ActionResult

class TracingTools(Tools[Context], Generic[Context]):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.executed: list[ExecutedAction] = []

    async def act(
        self,
        action: ActionModel,
        browser_session: Any,
        **kwargs
    ) -> ActionResult:
        # action is a one-of model; get the single tool name + params
        action_dump = action.model_dump(exclude_unset=True)
        action_name = next(iter(action_dump.keys()), "unknown")
        params = action_dump.get(action_name) or {}

        start = time.time()
        result = await super().act(
            action=action,
            browser_session=browser_session,
            **kwargs
        )
        end = time.time()

        self.executed.append(
            ExecutedAction(
                name=action_name,
                params=params if isinstance(params, dict) else {"value": params},
                start_s=start,
                end_s=end,
                result=result,
            )
        )
        return result