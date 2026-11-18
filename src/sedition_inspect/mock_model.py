"""Deterministic offline model provider for project verification."""

from __future__ import annotations

import anyio
from inspect_ai.model import (
    ChatMessage,
    GenerateConfig,
    ModelAPI,
    ModelOutput,
    ModelUsage,
    modelapi,
)
from inspect_ai.tool import ToolChoice, ToolInfo

PROVIDER = "sedition_mock"
MODEL = f"{PROVIDER}/model"
SLOW_MODEL = f"{PROVIDER}/slow"
DEFAULT_OUTPUT = "Default output from sedition_mock/model"


class SeditionMockAPI(ModelAPI):
    """Return one fixed response without credentials or network access."""

    async def generate(
        self,
        input: list[ChatMessage],
        tools: list[ToolInfo],
        tool_choice: ToolChoice,
        config: GenerateConfig,
    ) -> ModelOutput:
        del input, tools, tool_choice, config
        if self.model_name == "slow":
            await anyio.sleep(0.75)
        model_name = self.qualified_model_name or MODEL
        output = ModelOutput.from_content(model_name, DEFAULT_OUTPUT)
        output.usage = ModelUsage(input_tokens=1, output_tokens=1, total_tokens=2)
        return output

    async def count_text_tokens(self, text: str) -> int:
        return max(1, len(text.split()))


@modelapi(name=PROVIDER)
def sedition_mock() -> type[SeditionMockAPI]:
    return SeditionMockAPI
