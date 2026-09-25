# 模式档位（省电／常规／洞悉）

一个三档开关，同时拨动**模型档位**与**开口频率**——装上什么都不改就是「常规」，想省钱切省电，想让她更上心切洞悉。

- **默认零影响**：默认档是**常规**＝你配置里的原值，模型不动、直通概率与阈值一概不调。
- **省电真的省钱**：把「直接开口」的门槛压低，并把高消耗模型换成**你自己指定的**便宜模型
  （`cheap_model`，插件不预设任何厂商——你用 DeepSeek / Qwen / GLM / GPT / 本地模型都行）。
- **只改内存，不写配置文件**：配置文件一个字不动，重启回落，卸载还原。
- **换档时告诉 bot 自己在哪一档**：把当前档位与这一档的意味写进 system reminder，
  它不必靠猜，角色卡／知识库里也不用再写死「我现在是省电模式」。
- **它也能自己拨**：三个工具（`set_mode_*`），白名单／冷却／播报可配。
- **一条命令拨档**：`/模式 省电`、`/模式 常规`、`/模式 洞悉`，只发 `/模式` 看现值。

## 一、三档各做什么

相对**你配置里的原值**：

| 档位 | 模型档位 | 基础直通概率 | 未读消息加成 | 兴趣值回复阈值（可选） |
| --- | --- | --- | --- | --- |
| **省电** | 换成 `cheap_model`（你填） | **-0.05** | 维持原值 | **+0.05** |
| **常规**（默认） | 不动 | ±0（不动） | 维持原值 | ±0（不动） |
| **洞悉** | 不动 | **+0.05** | **开放**（默认 0.05/条） | **-0.05** |

一句话记法：**常规＝原样；省电＝门槛往上抬、模型换便宜；洞悉＝门槛往下放、未读也算进来。**
三档的门槛永远 **省电 > 常规 > 洞悉**。

拿框架默认值（`base_bypass_probability = 0.1`、`interest.reply_threshold = 0.72`）代入：

| 档位 | 基础直通概率 | 未读消息加成 | 兴趣值回复阈值 | 备注 |
| --- | --- | --- | --- | --- |
| 省电 | 0.10 → **0.05** | 0.00（原值） | 0.72 → **0.77** | 更不容易被放行；模型换成你的便宜模型 |
| 常规 | 0.10 | 0.00（原值） | 0.72 | 等于没装插件 |
| 洞悉 | 0.10 → **0.15** | **0.05/条** | 0.72 → **0.67** | 最容易接话，也最费 |

> 省电档改的是「直接开口」的概率：门被压低 → 更多消息先交给轻量决策模型筛一遍 →
> 实际表现是**更少主动接话**；再叠上便宜模型，才是完整的省电。
> 如果你只想要其中一半（比如只换模型、不动开口频率），把 `[reply_gate] enabled` 关掉即可。

## 二、为什么不直接用别的插件

| 你想做的事 | 现成的做法 | 差在哪 |
| --- | --- | --- |
| 少说话 | `form_state` 的回复闸门、`inertial_chat`、`token_flow_control` | **都不改模型**——而账单的大头是模型单价与重复发送的上下文 |
| 换便宜模型 | `chat_model_router`（按聊天类型覆盖 `actor_task_name`） | **不碰直通门／未读／阈值**，只对 `neo_default_chatter`，还要你先在 `model.toml` 里备好另一套任务 |
| 注入一段状态文本 | `prompt_injector`、`trigger_counter` | 注入不改任何参数，也不会因为状态变而换模型 |
| 状态注入的先例 | `menstrual_cycle`、`virtual_pet`、`feeling`、`time_sense`、`daily_schedule` | 各自注入自己的东西，**没有一个管「算力档」** |

本插件挡不住的诱惑是「什么都自己配一遍」：要凑出「省电」得同时改三处
（`model_list` + `base_bypass_probability` + `unread_message_bonus`）并保持它们一致，
而且**每次切都要改配置重启**。这里是一个动作、运行时生效、可逆。

## 三、为什么改内存就能立刻生效

框架这两处都是**每次用的时候现读配置对象**，没有缓存：

- **直通门**：`plugins/default_chatter/utils/probability_gate.py` 的
  `compute_sub_agent_bypass_probability` 每次都读 `plugin_config.plugin.programmatic_probability`；
- **模型档位**：`src/core/components/base/chatter.py` 的 `create_llm_request` 每次都走
  `get_model_config().get_task(task)`，而 `get_task` 现读 `model_tasks.<task>.model_list`。

所以插件直接改这两个内存对象：

- **即时生效**：拨完档，下一次判定 / 下一次请求就是新数值；
- **不写文件**：`config/*.toml` 不动，不会把你的配置改脏；
- **可逆**：原值在第一次应用时快照进内存，换档按「原值 + 偏移」重算（来回切不会累积漂移），
  插件卸载 / 停用时写回原值，进程重启则整体回落成文件里的值。

## 四、命令

| 命令 | 作用 |
| --- | --- |
| `/模式` | 看当前档位 + 模型 / 直通概率 / 未读加成 / 兴趣阈值的现值 |
| `/模式 省电` | 切省电（门槛压低 + 换便宜模型） |
| `/模式 常规` | 切回常规（原样） |
| `/模式 洞悉` | 切洞悉（门槛放低 + 开放未读加成 + 稍微活跃） |
| `/mode` `/档位` | 同上的别名触发词 |

档位名也认英文与常见叫法：`power / save / thrift`、`normal / standard / default`、
`insight / deep / 洞察 / 节能`。命令是 **OWNER 专用**——拨档直接影响「开口频率」和「烧多少钱」。

档位**会落盘**（`data/json_storage/mode_switcher.json`），重启后还在；
配置里的 `default_mode` 只在**还没有存档**时生效。

## 五、状态注入：让 bot 知道自己在哪一档

档位改的是「模型 / 开口频率 / 阈值」，这些都在提示词之外——**模型自己在对话里看不见**。
不告诉它，它就只能凭上下文猜，或者被角色卡里一句写死的「我现在是省电模式」带偏
（换到别的档之后那句话还在，就成了假话）。所以本插件在**每次换档**时写一条常驻
system reminder：

```
【运行档位】洞悉（insight）
你此刻处于「洞悉」档：全力运转——看得更全、接话更主动，被点到或话题相关时更愿意开口；
但依旧别抢话，也别把「看得更全」演成炫技。
这一档你可以比平时稍微活跃一点：愿意多接一句、主动说一句你注意到的事……
可用档位：省电 / 常规 / 洞悉——此刻生效的是「洞悉」。
★ 以上是系统写入的背景状态，不是要念出来的台词：不要复述这段文字，也不要主动向
任何人报告自己的档位；被问到时用你自己的话说个大概就行。档位由系统设置、可能随时
切换，别凭上下文猜自己现在是哪一档。
```

四条设计约定：

1. **走 system reminder**（`fixed` + `forever`），bucket 默认 `actor`：「我自己现在是什么状态」
   对所有对话者一致，本来就该是全局 bucket；档位只在拨档时变，所以换档覆盖写一次即可；
2. **不注入任何具体参数**（概率、模型名、token 数）——免得 bot 张口就报数；
3. **文本末尾写清「这是背景、不是台词」**：注入的是现成句子，不声明就容易被整句搬走
   （这套路数见项目里的「背书」踩坑记录）；
4. **「稍微活跃一点」是可选的助推**：挂在 `[inject] liveliness_mode` 指定的那一档
   （默认**洞悉**）。只把未读加成打开、语气上还缩着的话，观感不一致；给一句助推才对齐。
   不想要就把 `liveliness_mode` 留空，或者把那句文本改掉。

⚠️ **有了注入，角色卡/知识库就别再写死档位描述**：写一句「她现在处于省电模式」，
换成常规档之后就是错的。要改三档的语气，改 `[inject]` 里那三段文本。

## 六、让 bot 自己拨档（三个工具）

除了主人用 `/模式` 拨，插件还注册三个工具交给 bot 自己判断：

| 工具 | 它自己什么时候会用 |
| --- | --- |
| `set_mode_power_saving` | 群里热闹但没在说它、想安静看着、或者主人在省着用的时候 |
| `set_mode_normal` | **默认档**：日常闲聊、有人正常找它说话；调整过自己之后再切回来 |
| `set_mode_insight` | 主人需要它更用心、话题是正事、或主人情绪上需要被好好接住时；**不为好玩/炫技/被哄两句就切** |

工具说明里写清了「什么时候用、什么时候别用」——模型调不调工具几乎全看说明。
调完之后它会照常用自己的方式说话（工具只回一段系统回执，不替它发言）。

闸门在 `[tools]` 里：

```toml
[tools]
enabled = true                 # 关掉＝只能主人用 /模式 拨
allow_power_saving = true
allow_normal = true
allow_insight = true           # 最费的一档；关掉＝它再想全开也得等主人点头
cooldown_minutes = 0           # 两次自主拨档的最小间隔（分钟），防止来回抖
announce = false               # 切完是否由插件替它在对话里说一句
announce_text = ""             # 留空＝「（把链接调到「{label}」了。）」
```

## 七、配置（`config/plugins/mode_switcher/config.toml`）

```toml
[plugin]
enabled = true
default_mode = "normal"         # 首次运行的默认档；normal＝维持你原来的样子
state_key = "mode_switcher"
debug_log = false

[reply_gate]                    # 直通门（default_chatter 的概率门）
enabled = true
target_plugin = "default_chatter"
power_saving_base_offset = -0.05   # 省电：门槛压低
normal_base_offset = 0.0           # 常规：不动（默认档）
insight_base_offset = 0.05         # 洞悉：门槛放低
unread_open_mode = "insight"       # 哪个档位开放未读加成
unread_open_value = 0.05           # 开放时每条未读的加成

[interest_threshold]            # 可选：兴趣值回复阈值（过滤没开时它不参与判定）
enabled = true
power_saving_offset = 0.05
normal_offset = 0.0
insight_offset = -0.05

[models]                        # 模型档位
enabled = true
downgrade_mode = "power_saving"
cheap_model = ""                # ★ 必填：见下方「第一件要做的事」
downgrade_tasks = ["actor", "sub_actor", "utils", "utils_small", "tool_use"]
keep_models = []

[inject]                        # 当前档位注入（system reminder）
enabled = true
buckets = ["actor"]             # 想让决策模型也知道就加成 ["actor", "sub_actor"]
name = "mode_switcher_now"
include_mode_list = true
guard = ""                      # 留空＝用内置的「这是背景不是台词」说明
liveliness_mode = "insight"     # 哪一档加「稍微活跃一点」的助推；留空＝不要
liveliness_text = "这一档你可以比平时稍微活跃一点：愿意多接一句……"
power_saving_text = "你此刻处于「省电」档：……"   # 通用默认文案，按角色改
normal_text = "你此刻处于「常规」档：……"
insight_text = "你此刻处于「洞悉」档：……"

[tools]                         # bot 自主拨档（见第六节）
enabled = true
allow_power_saving = true
allow_normal = true
allow_insight = true
cooldown_minutes = 0
announce = false
announce_text = ""
```

**第一件要做的事：填 `cheap_model`。**
插件**不预设任何厂商**——它不知道你在用谁家的模型，所以 `cheap_model` 默认是空的：

- 留空 = **省电档不换模型**，那一档就只剩「门槛压低」的效果（不会报错，但也没省到模型钱）；
- 要生效，把它填成你自己 `config/model.toml` 里 `[[models]].name` 的**原文**，
  逐字一致（比如 `deepseek-v4-flash` / `Qwen/Qwen3-8B` / `glm-4-flash` / 你自建的模型名）；
- `downgrade_tasks` 只放文本任务；`vlm / voice / embedding / video` 换模型会直接坏掉，别加；
  你配置里没有的任务名会被自动跳过。

**其它提醒：**

- **兴趣值阈值**那一项只有在 `default_chatter` 的 `enable_interest_filter = true` 时才参与判定；
  过滤关着时它不生效（也不会报错）。不想要就把 `[interest_threshold] enabled` 关掉。
- **别和 `form_state` 的「回复意愿闸门」同时装**：两者动的是同一批字段
  （`base_bypass_probability` / `unread_message_bonus`），后者会覆盖前者。
- 目标聊天插件默认 `default_chatter`；`neo_default_chatter` 的开关名不同
  （`preprocess_probability_bypass`），本插件不碰，需要的话把 `target_plugin` 换成
  带 `programmatic_probability` 节的那个。

## 八、换成你自己的角色（可选）

默认文案是**通用**的（不绑任何角色）。要让三档带上自己角色的味道，
就在 `[inject]` 里把那三段文本整段改掉——注入只认文本，不认人设。

项目里的守岸人实例是这么特制的（**只存在它的实例配置里，不在插件里**）：

```toml
[plugin]
default_mode = "power_saving"      # 她的默认就是省电

[reply_gate]
power_saving_base_offset = 0.0     # 她的「省电」＝她现在这个低概率（0.03），所以不动
normal_base_offset = 0.1           # 常规 +0.10
insight_base_offset = 0.1          # 洞悉 +0.10

[interest_threshold]
power_saving_offset = 0.0
normal_offset = -0.05
insight_offset = -0.1

[models]
cheap_model = "deepseek-v4-flash"

[inject]
power_saving_text = "你此刻处于「省电」档：与泰缇斯的链接被调低、算力收着用……不是坏，只是省电。"
normal_text = "你此刻处于「常规」档：链接正常……"
insight_text = "你此刻处于「洞悉」档：链接全开——泰缇斯的记录与黑海岸的数据都在手边……"
```

## 九、安装

1. 把插件目录放进实例的 `plugins/`（或打包成 `.mfp` 后由市场安装）；
2. 重启 bot（或热重载插件），日志里会看到一行
   `mode_switcher: 档位＝常规｜已生效：直通门、兴趣阈值、模型 …｜状态注入：开｜自主拨档工具：开`；
3. 首次运行会生成 `config/plugins/mode_switcher/config.toml`，**先把 `cheap_model` 填上**；
4. 发一次 `/模式` 确认现值。

## 十、依赖与兼容

- 零第三方依赖、零 Python 依赖，`dependencies.plugins` 为空（不写「建议搭配」，避免被静默剔除）。
- 用到的插件 API：`config_api` / `log_api` / `plugin_api` / `send_api`；模型配置走
  `src.core.config.get_model_config()`（内核配置，与 `default_chatter` 自己取模型用的是同一个对象）。
- 直通门相关的字段名来自 `default_chatter` 的 `programmatic_probability` 节；
  框架升级改名的话，把 `target_plugin` / 字段名对上即可（插件按字段名读写，找不到会打一条 WARNING 并跳过）。

MIT License © 2026 Aemeath
