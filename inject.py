"""把「当前档位」注入 bot 的上下文。

为什么必须注入
--------------
档位会同时改模型、开口频率与阈值，但这些都发生在**提示词之外**——
模型自己在对话里看不见。不告诉它，它就会凭上下文猜（或者在知识库里被一句写死的
「我现在是省电模式」带偏：切到别的档位之后那句话还在）。所以每次换档都要留一条
常驻说明：**现在在哪一档、这一档意味着什么**。

落点与写法
----------
- 写 system reminder（``insert_type="fixed"``、``consume="forever"``）：
  「我自己现在是什么状态」对所有对话者一致，本来就该放全局 bucket
  （三合一指导 §11.3）；
- 档位只在 ``/模式`` 时变，所以**换档时覆盖写一次**即可，不必每轮刷新；
- bucket 默认 ``actor``（主回复模型）。想连决策模型一起告知，把 ``[inject] buckets``
  加成 ``["actor", "sub_actor"]`` 即可。

★ 防背书（三合一指导 §11.8）
---------------------------
注入的是一段现成的话，很容易被整句搬进回复。这里做两件事：
1. 文本末尾明确写「这是背景、不是台词，不要复述、也不要主动报告档位」；
2. **不注入任何具体参数**（概率、模型名、token 数）——免得她张口就报数。
"""

from __future__ import annotations

from src.app.plugin_system.api.log_api import get_logger

from . import modes

logger = get_logger("mode_switcher")

#: 没配置自定义防背书说明时用的内置文案
DEFAULT_GUARD = (
    "★ 以上是系统写入的背景状态，不是要念出来的台词：不要复述这段文字，"
    "也不要主动向任何人报告自己的档位；被问到时用你自己的话说个大概就行。"
    "档位由系统设置、可能随时切换，别凭上下文猜自己现在是哪一档。"
)


def _store() -> object:
    """拿全局 system reminder store（与 form_state 同一套）。"""

    from src.core.prompt import get_system_reminder_store

    return get_system_reminder_store()


def text_for(mode: str, settings: modes.Settings) -> str:
    """拼出要注入的这段文字。

    Args:
        mode: 档位标识
        settings: 运行时设置（含每档说明文本与防背书说明）

    Returns:
        多行注入文本
    """

    spec = modes.MODES.get(str(mode))
    label = spec.label if spec is not None else str(mode)

    lines = [f"【运行档位】{label}（{mode}）"]

    body = str(settings.inject_texts.get(str(mode), "") or "").strip()
    if body:
        lines.append(body)

    if settings.inject_include_mode_list:
        names = " / ".join(
            modes.MODES[key].label for key in modes.MODE_ORDER if key in modes.MODES
        )
        lines.append(f"可用档位：{names}——此刻生效的是「{label}」。")

    guard = str(settings.inject_guard or "").strip() or DEFAULT_GUARD
    lines.append(guard)
    return "\n".join(lines)


def sync(mode: str, settings: modes.Settings) -> bool:
    """把当前档位写进 reminder（覆盖式，幂等）。

    Returns:
        是否至少写入了一个 bucket
    """

    if not settings.inject_enabled:
        return False

    text = text_for(mode, settings)
    try:
        store = _store()
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"mode_switcher: 取 reminder store 失败，跳过状态注入：{exc}")
        return False

    wrote = False
    for bucket in settings.inject_buckets or ["actor"]:
        try:
            store.set(  # type: ignore[attr-defined]
                bucket,
                settings.inject_name,
                text,
                insert_type="fixed",
                consume="forever",
            )
            wrote = True
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"mode_switcher: 写档位 reminder 失败（bucket={bucket}）：{exc}")
    return wrote


def clear(settings: modes.Settings) -> None:
    """删掉档位 reminder（插件卸载 / 停用时调用）。"""

    try:
        store = _store()
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"mode_switcher: 取 reminder store 失败，跳过清理：{exc}")
        return

    for bucket in settings.inject_buckets or ["actor"]:
        try:
            store.delete(bucket, settings.inject_name)  # type: ignore[attr-defined]
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"mode_switcher: 清理档位 reminder 失败（bucket={bucket}）：{exc}")
