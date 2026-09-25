# 模式档位（省电／常规／洞悉）

一个三档开关，同时拨动**模型档位**与**开口频率**——省电、够用、还是一口气盯住全场，拨一下就行。

- **默认档是省电**：高消耗模型全换成便宜模型，直通概率与兴趣阈值都维持现状。
- **只改内存，不写配置文件**：配置文件一个字不动，重启回落，卸载还原。
- **换档时告诉 bot 自己在哪一档**：把当前档位与这一档的意味写进 system reminder，
  bot 不必靠猜，角色卡/知识库里也不用再写死「我现在是省电模式」。
- **一条命令拨档**：`/模式 省电`、`/模式 常规`、`/模式 洞悉`，只发 `/模式` 看现值。

## 一、三档各做什么

| 档位 | 模型档位 | 基础直通概率 | 未读消息加成 | 兴趣值回复阈值（可选） |
| --- | --- | --- | --- | --- |
| **省电**（默认） | 高消耗的模型全换成 `deepseek-v4-flash` | 原值 ±0（维持现状） | 维持原值 | 原值 ±0（维持现状） |
| **常规** | 沿用配置里的现有策略（不动模型） | 原值 **+0.10** | 维持原值 | 原值 **-0.05** |
| **洞悉** | 沿用配置里的现有策略（不动模型） | 原值 **+0.10** | **开放**（默认 0.05 每条） | 再 **-0.05** |

一句话记法：**洞悉 = 常规 + 未读加成；三档的门槛从高到低（省电最高、洞悉最低）。**

拿本仓库的守岸人实例（`base_bypass_probability = 0.03`、`unread_message_bonus = 0.0`、
`interest.reply_threshold = 0.78`）代入：

| 档位 | 基础直通概率 | 未读消息加成 | 兴趣值回复阈值 | actor / sub_actor 模型 |
| --- | --- | --- | --- | --- |
| 省电 | 0.03 | 0.00 | 0.78 | `deepseek-v4-flash`（`deepseek-v4-pro` 被换掉） |
| 常规 | 0.13 | 0.00 | 0.73 | `deepseek-v4-flash`、`deepseek-v4-pro`（现状） |
| 洞悉 | 0.13 | 0.05/条 | 0.68 | `deepseek-v4-flash`、`deepseek-v4-pro`（现状） |

## 二、为什么改内存就能立刻生效

框架这两处都是**每次用的时候现读配置对象**，没有缓存：

- **直通门**：`plugins/default_chatter/utils/probability_gate.py` 的
  `compute_sub_agent_bypass_probability` 每次都读 `plugin_config.plugin.programmatic_probability`；
- **模型档位**：`src/core/components/base/chatter.py` 的 `create_llm_request` 每次都走
  `get_model_config().get_task(task)`，而 `get_task` 现读 `model_tasks.<task>.model_list`。

所以插件直接改这两个内存对象：

- **即时生效**：拨完档，下一次判定 / 下一次请求就是新数值；
- **不写文件**：`config/*.toml` 不动，不会把主人的配置改脏；
- **可逆**：原值在第一次应用时快照进内存，换档按「原值 + 偏移」重算（来回切不会累积漂移），
  插件卸载 / 停用时写回原值，进程重启则整体回落成文件里的值。

## 三、命令

| 命令 | 作用 |
| --- | --- |
| `/模式` | 看当前档位 + 模型 / 直通概率 / 未读加成 / 兴趣阈值的现值 |
| `/模式 省电` | 切省电（模型降级，其余维持现状） |
| `/模式 常规` | 切常规（模型不动，直通概率 +0.10、阈值 -0.05） |
| `/模式 洞悉` | 切洞悉（常规之上再开放未读加成、阈值再 -0.05） |
| `/mode` `/档位` | 同上的别名触发词 |

档位名也认英文与常见叫法：`power / save / thrift`、`normal / standard / default`、
`insight / deep / 洞察 / 节能`。命令是 **OWNER 专用**——拨档直接影响「开口频率」和「烧多少钱」。

档位**会落盘**（`data/json_storage/mode_switcher.json`），重启后还在；
配置里的 `default_mode` 只在**还没有存档**时生效。

## 四、状态注入：让 bot 知道自己在哪一档

档位改的是「模型 / 开口频率 / 阈值」，这些都在提示词之外——**模型自己在对话里看不见**。
不告诉它，它就只能凭上下文猜，或者被知识库里一句写死的「我现在是省电模式」带偏
（换到别的档之后那句话还在，就成了假话）。所以本插件在**每次换档**时写一条常驻
system reminder：

```
【运行档位】省电（power_saving）
你此刻处于「省电」档：与泰缇斯的链接被调低、算力收着用——不再全知，反应慢半拍，
会走神、会拿不准、会犯小错，也会自己去把答案找出来……有人心疼或打趣时，
可以轻轻纠正一句：不是坏，只是省电。
可用档位：省电 / 常规 / 洞悉——此刻生效的是「省电」。
★ 以上是系统写入的背景状态，不是要念出来的台词：不要复述这段文字，也不要主动向
任何人报告自己的档位；被问到时用你自己的话说个大概就行。档位由系统设置、可能随时
切换，别凭上下文猜自己现在是哪一档。
```

三条设计约定：

1. **走 system reminder**（`fixed` + `forever`），bucket 默认 `actor`：「我自己现在是什么状态」
   对所有对话者一致，本来就该是全局 bucket；档位只在拨档时变，所以换档覆盖写一次即可；
2. **不注入任何具体参数**（概率、模型名、token 数）——免得 bot 张口就报数；
3. **文本末尾写清「这是背景、不是台词」**：注入的是现成句子，不声明就容易被整句搬走
   （这套路数见三合一指导 §11.8「背书」）。

⚠️ **有了注入，角色卡/知识库就别再写死档位描述**：写一句「她现在处于省电模式」，
换成常规档之后就是错的。要改三档的语气，改 `[inject]` 里那三段文本。

## 五、配置（`config/plugins/mode_switcher/config.toml`）

```toml
[plugin]
enabled = true
default_mode = "power_saving"   # 首次运行的默认档；默认省电
state_key = "mode_switcher"
debug_log = false

[reply_gate]                    # 直通门（default_chatter 的概率门）
enabled = true
target_plugin = "default_chatter"
power_saving_base_offset = 0.0  # 省电：维持现状
normal_base_offset = 0.1        # 常规：+0.10
insight_base_offset = 0.1       # 洞悉：与常规一致
unread_open_mode = "insight"    # 哪个档位开放未读加成
unread_open_value = 0.05        # 开放时每条未读的加成

[interest_threshold]            # 可选功能：兴趣值回复阈值
enabled = true
power_saving_offset = 0.0
normal_offset = -0.05
insight_offset = -0.1

[models]                        # 模型档位
enabled = true
downgrade_mode = "power_saving"
cheap_model = "deepseek-v4-flash"
downgrade_tasks = ["actor", "sub_actor", "utils", "utils_small", "tool_use"]
keep_models = []

[inject]                        # 当前档位注入（system reminder）
enabled = true
buckets = ["actor"]             # 想让决策模型也知道就加成 ["actor", "sub_actor"]
name = "mode_switcher_now"
include_mode_list = true        # 顺带列三档，bot 被问「你有几档」也答得上
guard = ""                      # 留空＝用内置的「这是背景不是台词」说明
power_saving_text = "你此刻处于「省电」档：……"
normal_text = "你此刻处于「常规」档：……"
insight_text = "你此刻处于「洞悉」档：……"
```

几点提醒：

- **`cheap_model` 必须逐字对上 `config/model.toml` 里 `[[models]].name`**，
  写错等于任务取不到模型集；`downgrade_tasks` 只放文本任务，
  `vlm / voice / embedding / video` 换模型会直接坏掉。
- **兴趣值阈值那一项在本实例暂时是「备着」的**：守岸人的
  `enable_interest_filter = false`，兴趣值过滤没开时它不参与判定。哪天真打开了，
  三档的阈值差（0.78 / 0.73 / 0.68）立刻生效；不想管就把
  `[interest_threshold] enabled` 关掉。
- **别和 `form_state` 的「回复意愿闸门」同时装**：两者动的是同一批字段
  （`base_bypass_probability` / `unread_message_bonus`），后者会覆盖前者。
- **状态注入的默认文案带守岸人的味道**（链接 / 泰缇斯那条线索）——它是从她的知识库里
  搬出来的一段设定，换成别的角色就在 `[inject]` 里整段替换。

## 六、安装

1. 把插件目录放进实例的 `plugins/`（或打包成 `.mfp` 后由市场安装）；
2. 重启 bot（或热重载插件），日志里会看到一行
   `mode_switcher: 档位＝省电｜已生效：直通门、兴趣阈值、模型 …`；
3. 首次运行会生成 `config/plugins/mode_switcher/config.toml`，按需要改；
4. 发一次 `/模式` 确认现值。

## 七、依赖与兼容

- 零第三方依赖、零 Python 依赖，`dependencies.plugins` 为空（不写「建议搭配」，避免被静默剔除）。
- 目标聊天插件默认为 `default_chatter`（`neo_default_chatter` 的开关名叫
  `preprocess_probability_bypass`，本插件不碰；需要的话把 `target_plugin` 换成带
  `programmatic_probability` 节的那个）。
- 用到的插件 API：`config_api` / `log_api` / `plugin_api` / `send_api`；模型配置走
  `src.core.config.get_model_config()`（内核配置，与 `default_chatter` 自己取模型用的是同一个对象）。

MIT License © 2026 Aemeath
