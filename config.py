"""mode_switcher 插件配置。

配置文件默认路径：``config/plugins/mode_switcher/config.toml``

三个档位（省电 / 常规 / 洞悉）各自做什么，全部写成**相对配置原值的偏移**，
这样本插件永远不会把「原值」弄丢：原值在第一次应用时快照进内存，
之后每次换档都按「原值 + 偏移」重算（见 :mod:`modes`）。

默认值就是给守岸人（本实例）定的一套：

============================  ==================  ==================  ==========================
档位                          模型                基础直通概率        未读消息加成 / 兴趣值回复阈值
============================  ==================  ==================  ==========================
省电（默认）                  高消耗的→flash      +0.00（维持现状）   原值 / +0.00（维持现状）
常规                          沿用现有策略        +0.10               原值 / -0.05
洞悉                          沿用现有策略        +0.10                开放 0.05 每条 / 再 -0.05
============================  ==================  ==================  ==========================

说明两点：

1. **直通概率**改的是 ``default_chatter``（名称可配）配置里的
   ``programmatic_probability.base_bypass_probability``；
   **未读加成**改的是同节的 ``unread_message_bonus``——「洞悉开放未读消息直通概率」
   就是把它从 0 抬到 ``unread_open_value``（默认 0.05/条，框架默认值）。
2. **兴趣值回复阈值**是「可选功能」：它改的是 ``interest.reply_threshold``。
   注意本实例默认 ``enable_interest_filter = false``，兴趣值过滤没开时这个数值
   不参与任何判定；等哪天把过滤打开，档位带来的阈值差就会立刻生效。
   不想要这一项就把 ``[interest_threshold] enabled`` 关掉。
"""

from __future__ import annotations

from typing import ClassVar

from src.core.components.base.config import BaseConfig, Field, SectionBase, config_section

#: 三档的标识（与 modes.MODES 的 key 一致）
_MODE_CHOICES = ["power_saving", "normal", "insight"]


class ReplyGateSection(SectionBase):
    """直通门（default_chatter 的概率门）按档位怎么调。"""

    enabled: bool = Field(
        default=True,
        description="是否按档位调整直通概率（关掉＝只动模型档位，不动开口频率）",
    )
    target_plugin: str = Field(
        default="default_chatter",
        description="要调整的聊天插件名（其配置需含 plugin.programmatic_probability 节）",
    )
    power_saving_base_offset: float = Field(
        default=0.0,
        description=(
            "省电档对「基础直通概率」的偏移（相对配置原值）。\n"
            "默认 0.0 ＝ 维持现状，不改开口频率。"
        ),
    )
    normal_base_offset: float = Field(
        default=0.1,
        description="常规档对「基础直通概率」的偏移（默认 +0.10）。",
    )
    insight_base_offset: float = Field(
        default=0.1,
        description=(
            "洞悉档对「基础直通概率」的偏移（默认 +0.10，与常规一致）。\n"
            "洞悉 = 常规 + 开放未读消息加成，所以这里通常和常规填同一个数。"
        ),
    )
    unread_open_mode: str = Field(
        default="insight",
        description=(
            "哪个档位开放「未读消息加成」（其它档位维持配置原值）。\n"
            "取值：power_saving / normal / insight；填空串表示任何档位都不动它。"
        ),
    )
    unread_open_value: float = Field(
        default=0.05,
        description=(
            "开放档位下「每条未读消息」的直通加成（框架默认 0.05）。\n"
            "≤0 表示沿用配置原值（等于不额外开放）。"
        ),
    )


class InterestThresholdSection(SectionBase):
    """可选功能：按档位调整兴趣值回复阈值。

    只在 ``default_chatter`` 的兴趣值过滤（``enable_interest_filter``）开启时
    才真正参与判定；过滤关着的时候，这里的数值只是「先备着」。
    """

    enabled: bool = Field(
        default=True,
        description=(
            "是否按档位调整兴趣值回复阈值（interest.reply_threshold）。\n"
            "本实例兴趣值过滤默认关闭，关着时改这个数没有可观察效果，但也不会有副作用。"
        ),
    )
    power_saving_offset: float = Field(
        default=0.0,
        description="省电档对兴趣值回复阈值的偏移（默认 0.0 ＝ 维持现状）。",
    )
    normal_offset: float = Field(
        default=-0.05,
        description="常规档对兴趣值回复阈值的偏移（默认 -0.05）。",
    )
    insight_offset: float = Field(
        default=-0.1,
        description="洞悉档对兴趣值回复阈值的偏移（默认 -0.10，在高到低里最低）。",
    )


class ModelsSection(SectionBase):
    """模型档位：哪个档位把「高消耗模型」换成便宜模型。"""

    enabled: bool = Field(
        default=True,
        description="是否按档位调整模型任务（config/model.toml 的 [model_tasks.*].model_list）",
    )
    downgrade_mode: str = Field(
        default="power_saving",
        description=(
            "哪个档位做「高消耗模型换便宜模型」（默认省电）。\n"
            "其余档位会把模型列表还原成配置原值（即沿用现在的策略）。"
        ),
    )
    cheap_model: str = Field(
        default="deepseek-v4-flash",
        description=(
            "降级时换上的模型名（config/model.toml 中 [[models]].name）。\n"
            "填错会算成「模型不存在」，任务取不到模型集——请与配置文件里的名字逐字一致。"
        ),
    )
    downgrade_tasks: list[str] = Field(
        default_factory=lambda: [
            "actor",
            "sub_actor",
            "utils",
            "utils_small",
            "tool_use",
        ],
        description=(
            "要参与降级的模型任务名列表（[model_tasks.*] 的节名）。\n"
            "默认只动文本任务；vlm / voice / embedding / video 这类换模型会直接坏掉，别加进来。"
        ),
    )
    keep_models: list[str] = Field(
        default_factory=list,
        description=(
            "白名单：模型列表里出现这些名字时**不替换**，原样留在列表最前面。\n"
            "留空＝列表里所有非 cheap_model 的模型都被换掉（默认行为）。\n"
            "例：keep_models = [\"qwen3-8b\"] 时 [\"qwen3-8b\",\"deepseek-v4-pro\"] → "
            "[\"qwen3-8b\",\"deepseek-v4-flash\"]。"
        ),
    )


class ModeSwitcherConfig(BaseConfig):
    """mode_switcher 插件配置模型。"""

    name: ClassVar[str] = "config"
    description: ClassVar[str] = "模式档位（省电／常规／洞悉）配置"

    @config_section("plugin", title="插件设置", tag="plugin")
    class PluginSection(SectionBase):
        """插件基础配置。"""

        enabled: bool = Field(
            default=True,
            description="是否启用插件（关掉＝卸载时还原所有档位改动）",
        )
        default_mode: str = Field(
            default="power_saving",
            description=(
                "默认档位，首次运行（还没有存档时）用它。\n"
                f"取值：{' / '.join(_MODE_CHOICES)}（即 省电 / 常规 / 洞悉）。"
            ),
        )
        state_key: str = Field(
            default="mode_switcher",
            description="档位持久化文件名（位于 data/json_storage/<state_key>.json）",
        )
        debug_log: bool = Field(
            default=False,
            description="是否在日志里输出每次应用的字段明细",
        )

    plugin: PluginSection = Field(default_factory=PluginSection)
    reply_gate: ReplyGateSection = Field(default_factory=ReplyGateSection)
    interest_threshold: InterestThresholdSection = Field(
        default_factory=InterestThresholdSection
    )
    models: ModelsSection = Field(default_factory=ModelsSection)
