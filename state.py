"""当前档位的持久化。

落在 ``data/json_storage/<state_key>.json``（与 form_state 同一套存储）：

.. code-block:: json

    {
      "mode": "normal",
      "updated_at": "2026-09-26 01:23:45"
    }

持久化的意义：进程重启后档位还在（默认档位只在**还没有存档**时生效）。
存档里出现认不出的档位（比如手改坏了、或者插件换了大版本）就回落默认档，
不抛异常——启动路径上不要因为一个坏文件把插件卡死。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Iterable

from src.app.plugin_system.api.log_api import get_logger
from src.kernel.storage import json_store

logger = get_logger("mode_switcher")

_TIME_FMT = "%Y-%m-%d %H:%M:%S"


async def load(state_key: str, default: str, valid: Iterable[str]) -> str:
    """读存档里的档位；读不到 / 不认识就返回默认档。"""

    allowed = set(valid)
    try:
        data: dict[str, Any] | None = await json_store.load(state_key)
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"mode_switcher: 读档位存档失败（回落默认档）：{exc}")
        return default

    if not isinstance(data, dict):
        return default

    mode = str(data.get("mode", "") or "").strip()
    if mode in allowed:
        return mode

    if mode:
        logger.warning(
            f"mode_switcher: 存档里的档位「{mode}」不认识，回落默认档「{default}」"
        )
    return default


async def save(state_key: str, mode: str, extra: dict[str, Any] | None = None) -> None:
    """写档位存档（写失败只警告，不影响本次切换在内存里已经生效）。"""

    payload: dict[str, Any] = {
        "mode": str(mode),
        "updated_at": datetime.now().strftime(_TIME_FMT),
    }
    if extra:
        payload.update(extra)
    try:
        await json_store.save(state_key, payload)
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"mode_switcher: 写档位存档失败：{exc}")
