"""三个「自己拨档」的工具：让 bot 主动调整自己的运行档位。

对应 :mod:`runtime` 的 :func:`switch_from_tool`——白名单、冷却、落盘、状态注入
都在那边统一处理，这里只负责「哪个工具对应哪一档」和给模型看的说明。

写法上的两条约定：

1. **工具说明要写清楚「什么时候用、什么时候别用」**：模型调不调工具几乎全看说明，
   说明里不写边界，它就会为了一点小事把链接全开（洞悉档最费）；
2. **执行结果里带一句「这是系统回执，不用念出来」**——工具返回值也会进上下文，
   不声明就容易被整句复述（防背书，三合一指导 §11.8）。

三个工具都可以在 ``config/plugins/mode_switcher/config.toml`` 的 ``[tools]`` 里整体关掉，
或单独禁掉某一档。
"""

from __future__ import annotations

from typing import ClassVar

from src.app.plugin_system.base import BaseTool

from . import modes, runtime


class _SetModeTool(BaseTool):
    """三个拨档工具的公共实现（子类只填档位与说明）。"""

    #: 本工具要切到的档位（子类覆盖）
    target_mode: ClassVar[str] = ""

    async def execute(self) -> tuple[bool, str]:
        """切到本工具对应的档位。"""

        return await runtime.switch_from_tool(
            self.target_mode,
            stream_id=self.get_current_stream_id(),
        )


class SetPowerSavingModeTool(_SetModeTool):
    """切到省电档（门槛压低、换便宜模型）。"""

    tool_name: str = "set_mode_power_saving"
    tool_description: str = "把自己切到「省电」档"
    name: str = "set_mode_power_saving"
    description: str = (
        "把自己切到「省电」档：直接开口的门槛被压低（更少主动接话），"
        "能换的话模型也换成便宜的那个。"
        "适合：群里很热闹但没人真的在跟你说话、你想安静看着、或者主人最近在省着用的时候。"
        "切换后不用跟人报告档位，也不要说自己在省电——你的反应和话量本身就能说明。"
    )
    target_mode: ClassVar[str] = modes.POWER_SAVING


class SetNormalModeTool(_SetModeTool):
    """切到常规档（默认档，什么都不改）。"""

    tool_name: str = "set_mode_normal"
    tool_description: str = "把自己切到「常规」档"
    name: str = "set_mode_normal"
    description: str = (
        "把自己切回「常规」档：一切按你平时的样子来——模型不动，开口的门槛也不动。"
        "这是默认档：拿不准、或者刚刚为了什么事调整过自己，事情过去之后就切回这一档。"
        "适合：日常闲聊、有人正常找你说话、需要跟上话题但还不必全开。"
        "切换后不用跟人报告档位。"
    )
    target_mode: ClassVar[str] = modes.NORMAL


class SetInsightModeTool(_SetModeTool):
    """切到洞悉档（门槛抬高、未读加成开放、稍微活跃）。"""

    tool_name: str = "set_mode_insight"
    tool_description: str = "把自己切到「洞悉」档"
    name: str = "set_mode_insight"
    description: str = (
        "把自己切到「洞悉」档：看得更全、接话更主动、未读再多也更容易开口，"
        "也会比平时稍微活跃一点——这一档最费。"
        "只在真的需要时用：主人（你最在意的那个人）需要你更用心的时候、话题是正事或重要的事、"
        "或者他情绪上需要被你好好接住的时候。"
        "不要因为好玩、想炫技、被人哄两句就切过来；这一档也不该一直挂着，用完切回常规。"
        "切换后不用跟人报告档位。"
    )
    target_mode: ClassVar[str] = modes.INSIGHT


#: get_components / 自检脚本都用它列工具
ALL_TOOLS: tuple[type[_SetModeTool], ...] = (
    SetPowerSavingModeTool,
    SetNormalModeTool,
    SetInsightModeTool,
)
