"""``/模式`` 命令：查看与切换运行档位（省电 / 常规 / 洞悉）。

用法（命令前缀由框架配置，默认 ``/``）：

.. code-block:: text

    /模式              看当前档位与各参数的现值
    /模式 省电          切到省电（模型降级，直通概率与阈值维持现状）
    /模式 常规          切到常规（模型不动，直通概率 +0.10、阈值 -0.05）
    /模式 洞悉          切到洞悉（常规之上再开放未读消息加成）
    /modes /档位        英文 / 中文别名

只有主人（OWNER）能用：拨档会直接改变「开口频率」与「烧多少钱」。
"""

from __future__ import annotations

from src.app.plugin_system.api.log_api import get_logger
from src.app.plugin_system.api.send_api import send_text
from src.app.plugin_system.base import BaseCommand, cmd_route
from src.app.plugin_system.types import PermissionLevel

from .. import modes, runtime

logger = get_logger("mode_switcher.command")

#: 只看状态的关键词
_STATUS_WORDS = ("", "状态", "status", "show", "now", "?", "？")


class ModeCommand(BaseCommand):
    """查看 / 切换运行档位。"""

    name: str = "mode"
    description: str = "查看或切换运行档位：省电 / 常规 / 洞悉（仅主人可用）"
    permission_level: PermissionLevel = PermissionLevel.OWNER

    @classmethod
    def match(cls, parts: list[str]) -> int:
        """支持 ``/mode``、``/模式``、``/档位`` 三种触发词。"""

        if not parts:
            return 0
        if parts[0].strip().lower() in ("mode", "modes", "模式", "档位", "档"):
            return 1
        return 0

    async def _reply(self, text: str) -> None:
        """给当前聊天流回消息。"""

        await send_text(text, stream_id=self.stream_id)

    @cmd_route()
    async def handle_root(self, target: str = "") -> tuple[bool, str]:
        """查看当前档位，或按参数切换档位。

        Args:
            target: 档位名（省电 / 常规 / 洞悉，或 power / normal / insight）；
                留空 = 只看状态
        """

        wanted = (target or "").strip()
        if wanted.lower() in _STATUS_WORDS:
            await self._reply(runtime.status_text())
            return True, "mode_status"

        ok, text = await runtime.switch(wanted)
        await self._reply(text)
        if ok:
            active = modes.current_mode()
            logger.info(f"档位已切到 {active}（由 {self.stream_id} 触发）")
            return True, f"mode_switched:{active}"
        return False, "unknown_mode"
