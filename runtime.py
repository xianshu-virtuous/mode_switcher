"""运行时编排：读档、应用档位、生成回复文本。

命令（:mod:`commands`）与插件入口（:mod:`plugin`）都只跟这一层打交道，
不直接碰 :mod:`modes` 的内部快照，方便替身测试。
"""

from __future__ import annotations

from src.app.plugin_system.api.log_api import get_logger

from . import modes
from . import state as mode_state

logger = get_logger("mode_switcher")

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


async def ensure_applied() -> bool:
    """补应用一次当前档位；返回直通门是否已经落到目标插件上。"""

    result = await apply_mode(modes.current_mode(), persist=False)
    if not settings().gate_enabled:
        return True
    return bool(result.gate)


async def restore() -> None:
    """还原所有档位改动（插件卸载时调用）。"""

    modes.restore()
