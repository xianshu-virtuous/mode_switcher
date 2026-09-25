"""运行时编排：读档、应用档位、生成回复文本。

命令（:mod:`commands`）与插件入口（:mod:`plugin`）都只跟这一层打交道，
不直接碰 :mod:`modes` 的内部快照，方便替身测试。
"""

from __future__ import annotations

import time

from src.app.plugin_system.api.log_api import get_logger
from src.app.plugin_system.api.send_api import send_text

from . import inject
from . import modes
from . import state as mode_state

logger = get_logger("mode_switcher")

#: 没配播报文案时用的那句（{label} 会被替换成档位名）
DEFAULT_ANNOUNCE = "（把链接调到「{label}」了。）"

#: 上一次「bot 自己拨档」的时刻（monotonic；只用于工具侧冷却）
_last_tool_switch_at: float = 0.0

_settings: modes.Settings | None = None


def configure(settings: modes.Settings) -> None:
    """注入运行时设置（同时转交给 :mod:`modes`）。"""

    global _settings
    _settings = settings
    modes.configure(settings)


def settings() -> modes.Settings:
    """拿设置；还没注入时给一份默认值，保证函数可独立调用。"""

    global _settings
    if _settings is None:
        _settings = modes.Settings()
        modes.configure(_settings)
    return _settings


def _fallback_mode() -> str:
    """默认档（配置里写坏了就用省电）。"""

    configured = str(settings().default_mode or "").strip()
    return configured if modes.is_mode(configured) else modes.POWER_SAVING


async def load_mode() -> str:
    """读持久化的档位，认不出则回落默认档。"""

    current = settings()
    return await mode_state.load(current.state_key, _fallback_mode(), set(modes.MODES))


async def apply_mode(mode: str, *, persist: bool = True) -> modes.ApplyResult:
    """应用档位（可选落盘）。

    Args:
        mode: 档位标识；非法值回落默认档
        persist: 是否写进 ``data/json_storage``

    Returns:
        :class:`modes.ApplyResult`
    """

    key = mode if modes.is_mode(mode) else _fallback_mode()
    result = modes.apply(key)
    if persist:
        await mode_state.save(settings().state_key, key)
    # 把「现在在哪一档」注入上下文：换档后模型自己才看得见（只写内存 reminder，不涉及磁盘）
    inject.sync(key, settings())
    return result


async def switch(text: str) -> tuple[bool, str]:
    """把用户给的档位名切过去。

    Args:
        text: 用户输入（省电 / 常规 / 洞悉 / power / normal / insight ...）

    Returns:
        ``(是否成功, 回复文本)``
    """

    key = modes.resolve_mode(text)
    if key is None:
        return False, modes.help_text()

    result = await apply_mode(key)
    lines = [f"已切到「{modes.mode_label(key)}」。"]
    if result.changes:
        lines.append("本次改动：" + "；".join(result.changes))
    elif settings().gate_enabled and not result.gate:
        lines.append("（目标聊天插件还没加载完，直通概率这部分稍后会自动补上）")
    lines.append("")
    lines.append(modes.describe(key))
    return True, "\n".join(lines)


def status_text() -> str:
    """当前档位与各参数现值。"""

    return modes.describe()


async def switch_from_tool(mode: str, *, stream_id: str = "") -> tuple[bool, str]:
    """LLM 工具入口：bot 自己拨档（走白名单与冷却）。

    Args:
        mode: 目标档位（档位标识或别名）
        stream_id: 当前聊天流；开着播报时用它在对话里说一句

    Returns:
        ``(是否成功, 回给模型的结果文本)``
    """

    global _last_tool_switch_at

    current = settings()
    key = modes.resolve_mode(mode)
    if key is None:
        return False, f"没有「{mode}」这个档位；可用：{modes.mode_names()}。"

    label = modes.mode_label(key)

    if not current.tools_enabled:
        return False, "自主切换档位现在是关着的，你只能保持当前档位。"
    if not current.tool_allows(key):
        return False, f"「{label}」档不允许你自己切，换别的档或者保持现状。"
    if key == modes.current_mode():
        return True, f"你现在已经在「{label}」档了，不需要再切一次。"

    cooldown = float(current.tool_cooldown_minutes)
    if cooldown > 0 and _last_tool_switch_at > 0:
        remain = cooldown * 60 - (time.monotonic() - _last_tool_switch_at)
        if remain > 0:
            minutes = max(1, (int(remain) + 59) // 60)
            return False, (
                f"刚换过档位，大约还要 {minutes} 分钟才能再切一次，先按现在这一档待着。"
            )

    result = await apply_mode(key)
    _last_tool_switch_at = time.monotonic()

    if current.tool_announce and stream_id:
        await _announce(label, stream_id, current.tool_announce_text)

    changes = "；".join(result.changes) if result.changes else "参数本来就是这一档的值"
    return True, (
        f"已切到「{label}」档（{changes}）。"
        "这条只是系统回执，不用念出来——照你现在的样子自然说话就行。"
    )


async def _announce(label: str, stream_id: str, template: str) -> None:
    """开着播报时，在对话里替她说一句（避免她切完沉默）。"""

    text = (template or DEFAULT_ANNOUNCE).format(label=label)
    try:
        await send_text(text, stream_id=stream_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"mode_switcher: 播报档位切换失败：{exc}")


async def ensure_applied() -> bool:
    """补应用一次当前档位；返回直通门是否已经落到目标插件上。"""

    result = await apply_mode(modes.current_mode(), persist=False)
    if not settings().gate_enabled:
        return True
    return bool(result.gate)


async def restore() -> None:
    """还原所有档位改动（插件卸载时调用）：先撤注入，再写回配置原值。"""

    inject.clear(settings())
    modes.restore()
