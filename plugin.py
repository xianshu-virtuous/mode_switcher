"""mode_switcher 插件入口：给 Bot 挂一个三档开关（省电 / 常规 / 洞悉）。

加载时做三件事：

1. 把插件配置翻译成运行时设置（:func:`_build_settings`）；
2. 读档位存档（读不到就用配置里的默认档，默认省电）并**应用**：
   模型档位 + 直通概率（+ 可选的兴趣值回复阈值）一次改到位；
3. 目标聊天插件（默认 ``default_chatter``）比自己晚加载时，开一个
   轮询补应用任务 —— 插件加载顺序是拓扑排序 + 字母序，正常情况下
   ``default_chatter`` 在 ``mode_switcher`` 之前，用不到这条兜底。

卸载时取消补应用任务并把所有改动还原成配置原值（:func:`runtime.restore`）。
"""

from __future__ import annotations

import asyncio

from src.app.plugin_system.api.log_api import get_logger
from src.app.plugin_system.base import BasePlugin, register_plugin

from . import modes, runtime
from .commands import ModeCommand
from .config import ModeSwitcherConfig

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
    )


@register_plugin
class ModeSwitcherPlugin(BasePlugin):
    """三档模式档位（省电 / 常规 / 洞悉）。"""

    plugin_name: str = "mode_switcher"
    plugin_description: str = (
        "一个三档开关，同时拨动「模型档位」与「开口频率」："
        "省电档把高消耗模型换成便宜模型、直通概率与兴趣阈值维持现状（默认档、最省 token）；"
        "常规档沿用配置里的模型策略、基础直通概率 +0.10、兴趣值回复阈值 -0.05；"
        "洞悉档在常规之上再开放未读消息加成（默认 0.05/条）、阈值再降 0.05。"
        "只改内存配置对象、不写配置文件，重启回落、卸载还原；/模式 随时拨档"
    )
    plugin_version: str = "1.0.0"
    configs: list[type] = [ModeSwitcherConfig]

    def __init__(self, config: object = None) -> None:
        super().__init__(config)  # type: ignore[arg-type]
        self._retry_task: asyncio.Task[None] | None = None

    def get_components(self) -> list[type]:
        """插件被关掉时不注册任何组件（等于整体下线）。"""

        if isinstance(self.config, ModeSwitcherConfig) and not self.config.plugin.enabled:
            return []
        return [ModeCommand]

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
