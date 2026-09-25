"""三档模式的定义与「落点」：把档位翻译成内存里的配置改动。

为什么可以只改内存
------------------
框架这两处都是**每次用的时候现读配置对象**，没有缓存快照：

- 直通门：``plugins/default_chatter/utils/probability_gate.py`` 的
  ``compute_sub_agent_bypass_probability`` 每次都读
  ``plugin_config.plugin.programmatic_probability``；
- 模型任务：``src/core/components/base/chatter.py`` 的 ``create_llm_request``
  每次都走 ``get_model_config().get_task(task)``，而 ``get_task`` 现读
  ``model_tasks.<task>.model_list``。

所以改内存字段即时生效，``config/*.toml`` 一个字不用动；进程重启回落成文件里的值，
再由插件加载时按当前档位重新应用。

三条保命约定
------------
1. **原值只采一次**：第一次应用时把目标字段的原值快照进 ``_prob_originals`` /
   ``_threshold_original`` / ``_model_originals``，之后每次换档都按「原值 + 偏移」
   重算 —— 档位来回切不会累积漂移。
2. **幂等**：``apply()`` 对同一档位重复调用结果一致；目标插件还没加载完时，
   对应的部分跳过并留一条 WARNING，等它起来后重试（见 :mod:`plugin`）。
3. **可逆**：``restore()`` 把快照原值写回，插件卸载 / 停用时调用。

⚠️ 与 ``form_state`` 的「回复意愿闸门」动的是同一批字段。同一个实例里两个都装，
后应用的那个会覆盖前一个（各自也只认得自己那份快照）。二选一。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from src.app.plugin_system.api import config_api, plugin_api
from src.app.plugin_system.api.log_api import get_logger

logger = get_logger("mode_switcher")

#: 三个档位的标识
POWER_SAVING = "power_saving"
NORMAL = "normal"
INSIGHT = "insight"

#: 官方顺序（命令帮助、文档里按这个排）
MODE_ORDER: tuple[str, ...] = (POWER_SAVING, NORMAL, INSIGHT)


# --------------------------------------------------------------------------- #
# 档位定义
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class ModeSpec:
    """一个档位是什么。"""

    key: str
    label: str
    tagline: str
    aliases: tuple[str, ...] = ()

    @property
    def display(self) -> str:
        return f"{self.label}（{self.key}）"


MODES: dict[str, ModeSpec] = {
    POWER_SAVING: ModeSpec(
        key=POWER_SAVING,
        label="省电",
        tagline=(
            "高消耗模型全换成便宜模型；直通概率与兴趣阈值都维持现状"
            "—— 最省 token 的一档，也是默认档"
        ),
        aliases=(
            "power",
            "save",
            "savepower",
            "thrift",
            "省电模式",
            "节能",
            "节能模式",
            "省token",
            "省token模式",
        ),
    ),
    NORMAL: ModeSpec(
        key=NORMAL,
        label="常规",
        tagline="模型沿用配置里的现有策略；基础直通概率 +0.10、兴趣值回复阈值 -0.05",
        aliases=("standard", "default", "normalmode", "常规模式", "普通", "普通模式"),
    ),
    INSIGHT: ModeSpec(
        key=INSIGHT,
        label="洞悉",
        tagline=(
            "常规之上再开放未读消息加成（默认 0.05/条），兴趣值回复阈值再降 0.05"
            "—— 最愿意接话的一档"
        ),
        aliases=("insight", "deep", "deepinsight", "洞悉模式", "洞察", "洞察模式"),
    ),
}


def _norm(text: str) -> str:
    """归一化：去空白、转小写、去下划线与连字符。"""

    return (
        "".join(str(text or "").strip().lower().split())
        .replace("_", "")
        .replace("-", "")
    )


_ALIAS_INDEX: dict[str, str] = {}
for _key, _spec in MODES.items():
    for _alias in (_key, _spec.label, *_spec.aliases):
        _ALIAS_INDEX[_norm(_alias)] = _key


def is_mode(text: str) -> bool:
    """是不是一个合法的档位标识。"""

    return str(text or "").strip() in MODES


def resolve_mode(text: str) -> str | None:
    """把用户输入（档位名 / 别名 / 中英文）解析成档位标识，认不出返回 None。"""

    return _ALIAS_INDEX.get(_norm(text))


def mode_label(mode: str) -> str:
    """档位标识 → 中文名（认不出就原样返回）。"""

    spec = MODES.get(str(mode or "").strip())
    return spec.label if spec is not None else str(mode or "未知")


def mode_names() -> str:
    """帮助文本里那句「可用档位」。"""

    parts = [f"{MODES[key].label}（{key}）" for key in MODE_ORDER if key in MODES]
    return " / ".join(parts)


# --------------------------------------------------------------------------- #
# 设置（由 plugin.py 从插件配置构造）
# --------------------------------------------------------------------------- #


@dataclass
class Settings:
    """运行时设置。"""

    default_mode: str = POWER_SAVING
    state_key: str = "mode_switcher"
    debug_log: bool = False

    # 直通门
    gate_enabled: bool = True
    target_plugin: str = "default_chatter"
    base_offsets: dict[str, float] = field(default_factory=dict)
    unread_open_mode: str = INSIGHT
    unread_open_value: float = 0.05

    # 兴趣值回复阈值（可选功能）
    threshold_enabled: bool = True
    threshold_offsets: dict[str, float] = field(default_factory=dict)

    # 模型档位
    models_enabled: bool = True
    downgrade_mode: str = POWER_SAVING
    cheap_model: str = "deepseek-v4-flash"
    downgrade_tasks: list[str] = field(default_factory=list)
    keep_models: list[str] = field(default_factory=list)

    # 状态注入（见 inject.py）
    inject_enabled: bool = True
    inject_buckets: list[str] = field(default_factory=lambda: ["actor"])
    inject_name: str = "mode_switcher_now"
    inject_texts: dict[str, str] = field(default_factory=dict)
    inject_include_mode_list: bool = True
    inject_guard: str = ""

    # 自主切换（LLM 工具，见 tools.py）
    tools_enabled: bool = True
    tool_allowed_modes: list[str] = field(
        default_factory=lambda: [POWER_SAVING, NORMAL, INSIGHT]
    )
    tool_cooldown_minutes: float = 0.0
    tool_announce: bool = False
    tool_announce_text: str = ""

    def base_offset(self, mode: str) -> float:
        """该档位对基础直通概率的偏移。"""

        return float(self.base_offsets.get(str(mode), 0.0))

    def threshold_offset(self, mode: str) -> float:
        """该档位对兴趣值回复阈值的偏移。"""

        return float(self.threshold_offsets.get(str(mode), 0.0))

    def downgrades_models(self, mode: str) -> bool:
        """该档位是否把高消耗模型换成便宜模型。"""

        return bool(self.models_enabled and str(mode) == self.downgrade_mode)

    def opens_unread(self, mode: str) -> bool:
        """该档位是否开放未读消息加成。"""

        return bool(
            self.unread_open_mode
            and str(mode) == self.unread_open_mode
            and float(self.unread_open_value) > 0.0
        )

    def tool_allows(self, mode: str) -> bool:
        """bot 能不能自己切到这一档。"""

        return bool(self.tools_enabled and str(mode) in set(self.tool_allowed_modes))


_settings: Settings | None = None

#: 原值快照（第一次应用时采集，换档不重采）
_prob_originals: dict[str, float] = {}
_threshold_original: float | None = None
_model_originals: dict[str, list[str]] = {}

#: 已经警告过的点（避免每轮刷日志）
_warned: set[str] = set()

#: 当前档位（apply() 成功调用后更新）
_current_mode: str = POWER_SAVING

_PROB_FIELDS = ("base_bypass_probability", "unread_message_bonus")


def configure(settings: Settings) -> None:
    """由插件在加载时注入设置。"""

    global _settings
    _settings = settings


def get_settings() -> Settings:
    """拿设置（还没注入时给一份默认值，保证函数可独立调用）。"""

    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


def current_mode() -> str:
    """当前档位。"""

    return _current_mode


# --------------------------------------------------------------------------- #
# 通用小工具
# --------------------------------------------------------------------------- #


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _signed(value: float) -> str:
    """带正负号的偏移展示（±0.00 表示中性）。"""

    number = float(value)
    if abs(number) < 1e-9:
        return "±0.00"
    return f"{number:+.2f}"


def _warn_once(key: str, message: str) -> None:
    if key in _warned:
        return
    _warned.add(key)
    logger.warning(f"mode_switcher: {message}")


def _float_attr(section: Any, name: str) -> float | None:
    value = getattr(section, name, None)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _set_attr(target: Any, name: str, value: Any) -> bool:
    """写字段（失败只警告一次，不让档位切换整个崩掉）。"""

    try:
        setattr(target, name, value)
        return True
    except Exception as exc:  # noqa: BLE001
        _warn_once(f"set:{name}", f"写入 {name} 失败：{exc}")
        return False


# --------------------------------------------------------------------------- #
# 目标对象（聊天插件配置 / 模型配置）
# --------------------------------------------------------------------------- #


def _plugin_config(target_plugin: str) -> Any | None:
    """拿目标聊天插件的配置对象（还没加载 / 卸载后返回 None）。"""

    if not target_plugin:
        return None
    try:
        cfg = config_api.get_config(target_plugin)
    except Exception:  # noqa: BLE001
        cfg = None
    if cfg is not None:
        return cfg
    try:
        plugin = plugin_api.get_plugin(target_plugin)
    except Exception:  # noqa: BLE001
        plugin = None
    return getattr(plugin, "config", None) if plugin is not None else None


def _prob_section(cfg: Any) -> Any | None:
    return getattr(getattr(cfg, "plugin", None), "programmatic_probability", None)


def _interest_section(cfg: Any) -> Any | None:
    return getattr(getattr(cfg, "plugin", None), "interest", None)


def _model_config() -> Any | None:
    """拿模型配置对象（``config/model.toml`` 的运行时映射）。"""

    try:
        from src.core.config import get_model_config
    except Exception as exc:  # noqa: BLE001
        _warn_once("import_model_config", f"取不到模型配置模块：{exc}")
        return None
    try:
        return get_model_config()
    except Exception as exc:  # noqa: BLE001
        _warn_once("model_config", f"模型配置尚未初始化：{exc}")
        return None


def _model_task(config: Any, task_name: str) -> Any | None:
    tasks = getattr(config, "model_tasks", None)
    if tasks is None:
        return None
    try:
        return tasks.get_task(task_name)
    except Exception:  # noqa: BLE001
        return None


def downgrade_list(models: list[str], cheap: str, keep: list[str]) -> list[str]:
    """把「高消耗模型」换成便宜模型。

    规则：白名单里的模型原样保留（顺序不变），其余全部替换成 ``cheap``；
    整张列表都在白名单里则原样返回（不动）。

    Args:
        models: 配置里的原始模型列表
        cheap: 降级时换上的模型名
        keep: 白名单（不替换的模型）

    Returns:
        降级后的模型列表
    """

    original = [str(item) for item in models if str(item).strip()]
    if not original or not cheap:
        return original
    kept = [item for item in original if item in keep]
    if len(kept) == len(original):
        return original
    result = list(kept)
    if cheap not in result:
        result.append(cheap)
    return result


# --------------------------------------------------------------------------- #
# 应用 / 还原
# --------------------------------------------------------------------------- #


@dataclass
class ApplyResult:
    """一次应用的记账。"""

    mode: str
    gate: bool = False
    threshold: bool = False
    models: bool = False
    changes: list[str] = field(default_factory=list)

    @property
    def touched(self) -> bool:
        """是否至少改到了一处。"""

        return self.gate or self.threshold or self.models

    def summary(self) -> str:
        """一行摘要，给日志用。"""

        parts: list[str] = []
        if self.gate:
            parts.append("直通门")
        if self.threshold:
            parts.append("兴趣阈值")
        if self.models:
            parts.append("模型")
        return "、".join(parts) if parts else "（目标插件未就绪，暂未改动）"


def _snapshot_prob(section: Any) -> None:
    for name in _PROB_FIELDS:
        if name in _prob_originals:
            continue
        value = _float_attr(section, name)
        if value is not None:
            _prob_originals[name] = value


def _snapshot_threshold(section: Any) -> None:
    global _threshold_original
    if _threshold_original is not None:
        return
    value = _float_attr(section, "reply_threshold")
    if value is not None:
        _threshold_original = value


def _apply_gate(mode: str, cfg: Any, settings: Settings, result: ApplyResult) -> None:
    """按档位写直通概率与未读加成。"""

    section = _prob_section(cfg)
    if section is None:
        _warn_once(
            "gate",
            f"没找到 {settings.target_plugin} 的 programmatic_probability 配置，"
            "直通概率档位暂不生效（等它加载完后会自动重试）",
        )
        return

    _snapshot_prob(section)
    result.gate = True

    base_original = _prob_originals.get("base_bypass_probability")
    if base_original is not None:
        offset = settings.base_offset(mode)
        base = _clamp01(base_original + offset)
        if _set_attr(section, "base_bypass_probability", round(base, 4)):
            result.changes.append(
                f"基础直通概率 {base_original:.2f}→{base:.2f}（{_signed(offset)}）"
            )

    unread_original = _prob_originals.get("unread_message_bonus")
    if unread_original is not None:
        if settings.opens_unread(mode):
            unread = _clamp01(settings.unread_open_value)
            note = f"未读消息加成 {unread_original:.2f}→{unread:.2f}（本档开放）"
        else:
            unread = _clamp01(unread_original)
            note = f"未读消息加成 {unread:.2f}（维持原值）"
        if _set_attr(section, "unread_message_bonus", round(unread, 4)):
            result.changes.append(note)


def _apply_threshold(mode: str, cfg: Any, settings: Settings, result: ApplyResult) -> None:
    """按档位写兴趣值回复阈值（可选功能）。"""

    section = _interest_section(cfg)
    if section is None:
        _warn_once(
            "threshold",
            f"没找到 {settings.target_plugin} 的 interest 配置，兴趣值阈值档位暂不生效",
        )
        return

    _snapshot_threshold(section)
    if _threshold_original is None:
        return

    offset = settings.threshold_offset(mode)
    value = _clamp01(_threshold_original + offset)
    if _set_attr(section, "reply_threshold", round(value, 4)):
        result.threshold = True
        result.changes.append(
            f"兴趣值回复阈值 {_threshold_original:.2f}→{value:.2f}（{_signed(offset)}）"
        )


def _apply_models(mode: str, settings: Settings, result: ApplyResult) -> bool:
    """按档位写模型任务列表（只有降级档会换模型，其余档位还原原值）。"""

    if not settings.models_enabled:
        return False
    config = _model_config()
    if config is None:
        return False

    names = list(dict.fromkeys([*_model_originals.keys(), *settings.downgrade_tasks]))
    downgrade = settings.downgrades_models(mode)
    touched = False

    for name in names:
        task = _model_task(config, name)
        if task is None:
            continue
        original = _model_originals.get(name)
        if original is None:
            value = getattr(task, "model_list", None)
            if not isinstance(value, list) or not value:
                continue
            original = [str(item) for item in value]
            _model_originals[name] = original

        if downgrade:
            target = downgrade_list(original, settings.cheap_model, settings.keep_models)
        else:
            target = list(original)

        current = getattr(task, "model_list", None)
        if list(current or []) != target:
            if _set_attr(task, "model_list", target):
                arrow = "→" if downgrade else "还原为"
                result.changes.append(f"{name} 模型 {original} {arrow} {target}")
        touched = True

    return touched


def apply(mode: str) -> ApplyResult:
    """把某个档位应用到内存配置上（幂等）。

    Args:
        mode: 档位标识（省电 / 常规 / 洞悉 的 key）；非法值回落到默认档

    Returns:
        :class:`ApplyResult`
    """

    global _current_mode

    settings = get_settings()
    key = str(mode or "").strip()
    if not is_mode(key):
        fallback = str(settings.default_mode or "").strip()
        key = fallback if is_mode(fallback) else POWER_SAVING

    result = ApplyResult(mode=key)
    cfg = (
        _plugin_config(settings.target_plugin)
        if (settings.gate_enabled or settings.threshold_enabled)
        else None
    )

    if settings.gate_enabled:
        _apply_gate(key, cfg, settings, result)
    if settings.threshold_enabled:
        _apply_threshold(key, cfg, settings, result)
    result.models = _apply_models(key, settings, result)

    _current_mode = key
    if settings.debug_log and result.changes:
        logger.info(f"mode_switcher: 应用「{mode_label(key)}」｜" + "；".join(result.changes))
    return result


def restore() -> None:
    """把快照里的原值写回（插件卸载 / 停用时调用）。"""

    settings = get_settings()
    cfg = _plugin_config(settings.target_plugin)
    if cfg is not None:
        prob = _prob_section(cfg)
        if prob is not None:
            for name, value in _prob_originals.items():
                _set_attr(prob, name, value)
        interest = _interest_section(cfg)
        if interest is not None and _threshold_original is not None:
            _set_attr(interest, "reply_threshold", _threshold_original)

    config = _model_config()
    if config is not None:
        for name, models in _model_originals.items():
            task = _model_task(config, name)
            if task is not None:
                _set_attr(task, "model_list", list(models))


def reset_snapshots() -> None:
    """丢掉原值快照（自检脚本用；正常运行时不需要）。"""

    global _threshold_original, _settings
    _prob_originals.clear()
    _model_originals.clear()
    _warned.clear()
    _threshold_original = None
    _settings = None


# --------------------------------------------------------------------------- #
# 状态文本
# --------------------------------------------------------------------------- #


def describe(mode: str | None = None) -> str:
    """生成「当前档位 + 各参数现值」的多行文本（/模式 的回复）。"""

    settings = get_settings()
    key = mode if is_mode(mode or "") else current_mode()
    spec = MODES.get(key)
    lines: list[str] = [f"【运行档位】{spec.display if spec else key}"]
    if spec is not None:
        lines.append(f"· 这一档：{spec.tagline}")

    # 模型
    if not settings.models_enabled:
        lines.append("· 模型：本插件不动模型（配置里已关）")
    elif settings.downgrades_models(key):
        tasks = "、".join(settings.downgrade_tasks) or "（未配置任务）"
        lines.append(f"· 模型：{tasks} → {settings.cheap_model}（高消耗模型已换成便宜模型）")
        for name, original in _model_originals.items():
            now = downgrade_list(original, settings.cheap_model, settings.keep_models)
            lines.append(f"    - {name}：{'、'.join(original)} → {'、'.join(now)}")
    else:
        lines.append("· 模型：沿用配置里的现有策略（不降级）")

    # 直通概率
    if not settings.gate_enabled:
        lines.append("· 直通概率：本插件不动（配置里已关）")
    else:
        base = _prob_originals.get("base_bypass_probability")
        if base is None:
            lines.append(
                f"· 直通概率：暂时读不到 {settings.target_plugin} 的配置"
                "（等它加载完会自动补上）"
            )
        else:
            value = _clamp01(base + settings.base_offset(key))
            lines.append(
                f"· 基础直通概率：{base:.2f} → {value:.2f}"
                f"（{_signed(settings.base_offset(key))}）"
            )
        unread = _prob_originals.get("unread_message_bonus")
        if unread is not None:
            if settings.opens_unread(key):
                lines.append(
                    f"· 未读消息加成：{unread:.2f} → "
                    f"{_clamp01(settings.unread_open_value):.2f}/条（本档开放）"
                )
            else:
                lines.append(f"· 未读消息加成：{unread:.2f}/条（维持原值）")

    # 兴趣值回复阈值
    if not settings.threshold_enabled:
        lines.append("· 兴趣值回复阈值：本插件不动（配置里已关）")
    elif _threshold_original is None:
        lines.append(
            f"· 兴趣值回复阈值：暂时读不到 {settings.target_plugin} 的配置"
            "（等它加载完会自动补上）"
        )
    else:
        value = _clamp01(_threshold_original + settings.threshold_offset(key))
        lines.append(
            f"· 兴趣值回复阈值：{_threshold_original:.2f} → {value:.2f}"
            f"（{_signed(settings.threshold_offset(key))}）"
        )
        lines.append("    （兴趣值过滤没开时这一项不参与判定，先备着）")

    lines.append(
        "· 拨档：/模式 省电 ｜ /模式 常规 ｜ /模式 洞悉"
        "（只发 /模式 就是看这份状态）"
    )
    return "\n".join(lines)


def help_text() -> str:
    """认不出参数时的帮助。"""

    lines = [f"认不出这个档位。可用：{mode_names()}"]
    for key in MODE_ORDER:
        spec = MODES.get(key)
        if spec is not None:
            lines.append(f"· {spec.label}：{spec.tagline}")
    lines.append("用法：/模式 <省电|常规|洞悉>；只发 /模式 看当前状态。")
    return "\n".join(lines)
