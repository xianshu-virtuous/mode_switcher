"""mode_switcher 插件入口：给 Bot 挂一个三档开关（省电 / 常规 / 洞悉）。

加载时做三件事：

1. 把插件配置翻译成运行时设置（:func:`_build_settings`）；
2. 读档位存档（读不到就用配置里的默认档，默认**常规**＝维持原样）并**应用**：
   模型档位 + 直通概率（+ 可选的兴趣值回复阈值）一次改到位，
   同时把「当前在哪一档」写进 system reminder（:mod:`inject`）——
   模型自己看不见档位，不告诉它就只能靠猜；
3. 目标聊天插件（默认 ``default_chatter``）比自己晚加载时，开一个
   轮询补应用任务 —— 插件加载顺序是拓扑排序 + 字母序，正常情况下
   ``default_chatter`` 在 ``mode_switcher`` 之前，用不到这条兜底。

另外注册四个组件：``/模式`` 命令（主人用）、以及三个拨档工具
（``set_mode_power_saving`` / ``set_mode_normal`` / ``set_mode_insight``，bot 自己用）。

卸载时取消补应用任务并把所有改动还原成配置原值（:func:`runtime.restore`）。
"""

from __future__ import annotations

import asyncio

from src.app.plugin_system.api.log_api import get_logger
from src.app.plugin_system.base import BasePlugin, register_plugin

from . import modes, runtime
from .commands import ModeCommand
from .config import ModeSwitcherConfig
from .tools import ALL_TOOLS, SetInsightModeTool, SetNormalModeTool, SetPowerSavingModeTool

logger = get_logger("mode_switcher")

#: 目标插件晚加载时的补应用节奏（20 次 × 3 秒 = 最多等 1 分钟）
_RETRY_ATTEMPTS = 20
_RETRY_INTERVAL = 3.0


def _build_settings(config: ModeSwitcherConfig) -> modes.Settings:
    """把插件配置翻译成运行时设置。"""

    plugin = config.plugin
    gate = config.reply_gate
    threshold = config.interest_threshold
    models_cfg = config.models
    inject = config.inject
    tools = config.tools

    return modes.Settings(
        default_mode=str(plugin.default_mode or "").strip(),
        state_key=str(plugin.state_key or "mode_switcher").strip(),
        debug_log=bool(plugin.debug_log),
        gate_enabled=bool(gate.enabled),
        target_plugin=str(gate.target_plugin or "").strip(),
        base_offsets={
            modes.POWER_SAVING: float(gate.power_saving_base_offset),
            modes.NORMAL: float(gate.normal_base_offset),
            modes.INSIGHT: float(gate.insight_base_offset),
        },
        unread_open_mode=str(gate.unread_open_mode or "").strip(),
        unread_open_value=float(gate.unread_open_value),
        threshold_enabled=bool(threshold.enabled),
        threshold_offsets={
            modes.POWER_SAVING: float(threshold.power_saving_offset),
            modes.NORMAL: float(threshold.normal_offset),
            modes.INSIGHT: float(threshold.insight_offset),
        },
        models_enabled=bool(models_cfg.enabled),
        downgrade_mode=str(models_cfg.downgrade_mode or "").strip(),
        cheap_model=str(models_cfg.cheap_model or "").strip(),
        downgrade_tasks=[
            str(task).strip() for task in models_cfg.downgrade_tasks if str(task).strip()
        ],
        keep_models=[
            str(model).strip() for model in models_cfg.keep_models if str(model).strip()
        ],
        inject_enabled=bool(inject.enabled),
        inject_buckets=[
            str(bucket).strip() for bucket in inject.buckets if str(bucket).strip()
        ]
        or ["actor"],
        inject_name=str(inject.name or "mode_switcher_now").strip(),
        inject_texts={
            modes.POWER_SAVING: str(inject.power_saving_text or ""),
            modes.NORMAL: str(inject.normal_text or ""),
            modes.INSIGHT: str(inject.insight_text or ""),
        },
        inject_include_mode_list=bool(inject.include_mode_list),
        inject_guard=str(inject.guard or ""),
        inject_liveliness_mode=str(inject.liveliness_mode or "").strip(),
        inject_liveliness_text=str(inject.liveliness_text or ""),
        tools_enabled=bool(tools.enabled),
        tool_allowed_modes=[
            key
            for key, allowed in (
                (modes.POWER_SAVING, tools.allow_power_saving),
                (modes.NORMAL, tools.allow_normal),
                (modes.INSIGHT, tools.allow_insight),
            )
            if allowed
        ],
        tool_cooldown_minutes=float(tools.cooldown_minutes),
        tool_announce=bool(tools.announce),
        tool_announce_text=str(tools.announce_text or ""),
    )


@register_plugin
class ModeSwitcherPlugin(BasePlugin):
    """三档模式档位（省电 / 常规 / 洞悉）。"""

    plugin_name: str = "mode_switcher"
    plugin_description: str = (
        "一个三档开关，同时拨动「模型档位」与「开口频率」："
        "常规档＝维持你配置里的原值（默认档，装上什么都不改就是这一档）；"
        "省电档把直接开口的门槛压低（基础直通概率 -0.05、兴趣阈值 +0.05），"
        "并把高消耗模型换成你自己指定的便宜模型（cheap_model）；"
        "洞悉档反过来（直通概率 +0.05、阈值 -0.05），开放未读消息加成，"
        "并可选注入一句「稍微活跃一点」的提示。"
        "换档时把「当前在哪一档」注入 system reminder，bot 自己知道状态；"
        "另给 bot 三个工具，让它按情况自己调档（白名单 + 冷却可配）；"
        "只改内存配置对象、不写配置文件，重启回落、卸载还原；/模式 随时拨档"
    )
    plugin_version: str = "1.3.0"
    configs: list[type] = [ModeSwitcherConfig]

    def __init__(self, config: object = None) -> None:
        super().__init__(config)  # type: ignore[arg-type]
        self._retry_task: asyncio.Task[None] | None = None

    def get_components(self) -> list[type]:
        """插件被关掉时不注册任何组件（等于整体下线）。"""

        config = self.config
        if isinstance(config, ModeSwitcherConfig) and not config.plugin.enabled:
            return []

        components: list[type] = [ModeCommand]
        if isinstance(config, ModeSwitcherConfig):
            if config.tools.enabled:
                components.extend(ALL_TOOLS)
        else:
            components.extend(ALL_TOOLS)
        return components

    async def on_plugin_loaded(self) -> None:
        """注入设置、读档、应用档位。"""

        config = self.config
        if not isinstance(config, ModeSwitcherConfig):
            logger.error("mode_switcher: 配置加载失败，插件不生效")
            return
        if not config.plugin.enabled:
            logger.info("mode_switcher: 配置里已禁用，跳过初始化")
            return

        runtime.configure(_build_settings(config))

        mode = await runtime.load_mode()
        result = await runtime.apply_mode(mode)

        detail = f"｜{'；'.join(result.changes)}" if result.changes else ""
        logger.info(
            f"mode_switcher: 档位＝{modes.mode_label(mode)}"
            f"｜已生效：{result.summary()}{detail}"
            f"｜状态注入：{'开' if runtime.settings().inject_enabled else '关'}"
            f"｜自主拨档工具：{'开' if runtime.settings().tools_enabled else '关'}"
        )

        if runtime.settings().gate_enabled and not result.gate:
            self._retry_task = asyncio.create_task(self._retry_apply())

    async def _retry_apply(self) -> None:
        """目标聊天插件比本插件晚加载时的补应用（正常情况下用不到）。"""

        for _ in range(_RETRY_ATTEMPTS):
            await asyncio.sleep(_RETRY_INTERVAL)
            try:
                applied = await runtime.ensure_applied()
            except Exception as exc:  # noqa: BLE001
                logger.warning(f"mode_switcher: 补应用档位失败：{exc}")
                return
            if applied:
                logger.info(
                    f"mode_switcher: 已补应用「{modes.mode_label(modes.current_mode())}」"
                    "（目标聊天插件刚加载完）"
                )
                return

        logger.warning(
            "mode_switcher: 一直等不到目标聊天插件，直通概率这部分暂时没落上去；"
            "它加载完之后发一次 /模式 重新拨档即可"
        )

    async def on_plugin_unloaded(self) -> None:
        """停掉补应用任务，并把所有档位改动还原成配置原值。"""

        task = self._retry_task
        if task is not None and not task.done():
            task.cancel()
        self._retry_task = None

        try:
            await runtime.restore()
            logger.info("mode_switcher: 已还原模型与概率门的配置原值")
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"mode_switcher: 还原档位改动失败：{exc}")
