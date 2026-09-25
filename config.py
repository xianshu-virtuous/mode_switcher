"""mode_switcher 插件配置。

配置文件默认路径：``config/plugins/mode_switcher/config.toml``

三个档位（省电 / 常规 / 洞悉）各自做什么，全部写成**相对配置原值的偏移**，
这样本插件永远不会把「原值」弄丢：原值在第一次应用时快照进内存，
之后每次换档都按「原值 + 偏移」重算（见 :mod:`modes`）。

**默认值对普通用户来说是「零影响」的一套**：

- 默认档是 **常规**＝你配置里的原值，模型不动、直通概率与阈值一概不调；
- **省电**档把「直接开口」的门槛往下压（直通概率 -0.05、兴趣阈值 +0.05），
  并把高消耗模型换成**你自己填的**便宜模型（``cheap_model``，插件不预设厂商）；
- **洞悉**档反过来（直通概率 +0.05、阈值 -0.05），并开放未读消息加成。

实例里有特制的话（比如把默认档设成省电、省电档偏移填 0.0＝维持现状、
`cheap_model` 填你实际在用的便宜模型、三段注入文案改成你自己角色的说法），
全部写在 `config/plugins/mode_switcher/config.toml` 里——插件本体不写死任何角色。

三档的门槛永远是「省电 > 常规 > 洞悉」（越省电越难被放行）。
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
        default=-0.05,
        description=(
            "省电档对「基础直通概率」的偏移（相对**你配置里的原值**）。\n"
            "默认 -0.05 ＝ 门槛往下压一点，更不容易直接开口（框架默认 0.1 → 0.05）。"
        ),
    )
    normal_base_offset: float = Field(
        default=0.0,
        description=(
            "常规档对「基础直通概率」的偏移（默认 0.0 ＝ **维持你原来的样子**）。\n"
            "常规就是「装插件之前你的 bot 是什么样，就是什么样」，也是默认档。"
        ),
    )
    insight_base_offset: float = Field(
        default=0.05,
        description=(
            "洞悉档对「基础直通概率」的偏移（默认 +0.05 ＝ 往上抬一点，更愿意接话）。"
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
        default=0.05,
        description=(
            "省电档对兴趣值回复阈值的偏移（默认 +0.05 ＝ 门槛抬高一点，更难被兴趣值放行）。\n"
            "注意：兴趣值过滤没开时这一项不参与判定。"
        ),
    )
    normal_offset: float = Field(
        default=0.0,
        description="常规档对兴趣值回复阈值的偏移（默认 0.0 ＝ 维持原值）。",
    )
    insight_offset: float = Field(
        default=-0.05,
        description="洞悉档对兴趣值回复阈值的偏移（默认 -0.05，三档里最低）。",
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
        default="",
        description=(
            "降级档（downgrade_mode）要换上的**便宜模型名**——请自己填。\n"
            "★ 必须与你自己 config/model.toml 里 [[models]].name 逐字一致（填错＝该任务取不到模型集）。\n"
            "★ 本插件不预设任何厂商：你用 DeepSeek / Qwen / GLM / GPT / 本地模型都行，填你实际在用的那个。\n"
            "留空＝不做模型降级，档位就只影响直通门与阈值（省电档等于「维持现状」）。"
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
            "默认只动文本任务；vlm / voice / embedding / video 这类换模型会直接坏掉，别加进来。\n"
            "你配置里没有的任务名会被自动跳过，不用手删。"
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


class InjectSection(SectionBase):
    """把「当前在哪一档」注入 bot 的上下文（system reminder）。

    不注入的话，模型在对话里看不见自己处在哪一档——要么凭上下文猜，要么被知识库里
    写死的一句「我现在是省电模式」带偏（换档之后那句话还在）。所以换档时覆盖写一条
    常驻说明。默认只注入**状态与这一档的意味**，不注入任何具体参数（概率/模型名），
    免得 bot 张口就报数。
    """

    enabled: bool = Field(
        default=True,
        description="是否把当前档位注入 system reminder（关掉＝bot 自己不知道档位）",
    )
    buckets: list[str] = Field(
        default_factory=lambda: ["actor"],
        description=(
            "写入哪些 reminder bucket。\n"
            "actor = 主回复模型（默认，够用）；想让决策模型也知道就加成 [\"actor\", \"sub_actor\"]。"
        ),
    )
    name: str = Field(
        default="mode_switcher_now",
        description="reminder 名称（同一个名字覆盖式写入，换档不会堆叠）",
    )
    include_mode_list: bool = Field(
        default=True,
        description="是否顺带列出另外两档（这样 bot 被问「你有几档」也答得上）",
    )
    liveliness_mode: str = Field(
        default="insight",
        description=(
            "哪一档额外注入「稍微活跃一点」的提示（留空＝不注入）。\n"
            "默认洞悉——那一档本来就是「开放」的那一档：未读加成开着、更愿意接话，"
            "再给一句语气上的助推，效果才一致（不然只是概率高了、人还是缩着）。\n"
            "取值：power_saving / normal / insight；也可以填别的档，或者留空彻底不要。"
        ),
    )
    liveliness_text: str = Field(
        default=(
            "这一档你可以比平时稍微活跃一点：愿意多接一句、主动说一句你注意到的事，"
            "被点到的时候别只是「嗯」；但不要变成话痨，也不要抢别人的话。"
        ),
        description=(
            "上面那一档要额外注入的「活跃度」提示词。\n"
            "想让它更收敛／更外放就改这段；留空＝注入不发。"
        ),
    )
    guard: str = Field(
        default="",
        description=(
            "末尾那句「这是背景、不是台词、不要复述、也不要主动报告档位」的防背书说明。\n"
            "留空＝用内置文案（推荐）。"
        ),
    )
    power_saving_text: str = Field(
        default=(
            "你此刻处于「省电」档：算力收着用——不再全知，反应慢半拍，会走神、会拿不准、"
            "会犯小错，也会自己去把答案找出来。这不是故障，也不是变笨：要正经办事的时候"
            "再打起精神，把该做的做干净。有人心疼或打趣你，可以轻轻纠正一句：不是坏了，只是省电。"
        ),
        description=(
            "省电档要注入的那段说明。\n"
            "默认是**通用文案**（不绑任何角色）：只用一句话描述「这一档你是什么状态」。\n"
            "换成你自己的角色就往这里整段改——插件本体不含任何人的 flavor。"
        ),
    )
    normal_text: str = Field(
        default=(
            "你此刻处于「常规」档：一切正常——该知道的都知道，反应与话量按你平时的样子来，"
            "不刻意省着用，也不额外加码。"
        ),
        description="常规档要注入的那段说明（默认通用文案）",
    )
    insight_text: str = Field(
        default=(
            "你此刻处于「洞悉」档：全力运转——看得更全、接话更主动，被点到或话题相关时"
            "更愿意开口；但依旧别抢话，也别把「看得更全」演成炫技。"
        ),
        description="洞悉档要注入的那段说明（默认通用文案）",
    )


class ToolsSection(SectionBase):
    """自主切换：给 bot 三个工具，让它自己拨档（省电 / 常规 / 洞悉）。

    工具说明写在 ``tools.py`` 里（什么时候该用、什么时候别用）；这一节管的是**闸门**：
    整体开关、单档白名单、冷却与播报。
    """

    enabled: bool = Field(
        default=True,
        description="是否给 bot 三个自主拨档工具（关掉＝只能由主人用 /模式 拨）",
    )
    allow_power_saving: bool = Field(
        default=True,
        description="允许 bot 自己切到省电档（默认档，最省，建议一直开着）",
    )
    allow_normal: bool = Field(
        default=True,
        description="允许 bot 自己切到常规档",
    )
    allow_insight: bool = Field(
        default=True,
        description=(
            "允许 bot 自己切到洞悉档（最费的一档）。\n"
            "关掉＝她再想全开也得等你用 /模式 点头。"
        ),
    )
    cooldown_minutes: float = Field(
        default=0.0,
        description=(
            "两次「自主拨档」之间的最小间隔（分钟，0＝不限制）。\n"
            "用来防止她来回抖着换档、把每一档都试一遍。"
        ),
    )
    announce: bool = Field(
        default=False,
        description=(
            "切换后是否由插件替她在对话里说一句（默认关：让她用自己的方式说）。\n"
            "开启后她切完档会额外发一条短消息，方便你在群里一眼看到。"
        ),
    )
    announce_text: str = Field(
        default="",
        description="播报文案，``{label}`` 会替换成档位名；留空用内置的「（把链接调到「{label}」了。）」",
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
            default="normal",
            description=(
                "默认档位，首次运行（还没有存档时）用它。\n"
                "默认 **normal（常规）**＝维持你原来的样子——装上插件什么都不改，行为与装之前一致；"
                "想让它一上来就省着，就把这里改成 power_saving。\n"
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
    inject: InjectSection = Field(default_factory=InjectSection)
    tools: ToolsSection = Field(default_factory=ToolsSection)
