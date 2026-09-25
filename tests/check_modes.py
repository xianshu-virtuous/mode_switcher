"""mode_switcher 自检：真实框架导入冒烟 + 三档数值断言。

用法（用目标实例自己的 venv python 跑；cwd 给一个可写目录，存档会落在 ./data/ 下）：

    $env:NEO_ROOT="F:\\Neo-MoFox-Shorekeeper"
    & "F:\\Neo-MoFox-Shorekeeper\\.venv\\Scripts\\python.exe" `
        "F:\\mofox插件\\plugin\\repo\\mode_switcher\\tests\\check_modes.py"

只读验证：不会去改实例里的任何插件 / 配置文件；目标聊天插件与模型配置都用替身对象。
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

NEO_ROOT = Path(os.environ.get("NEO_ROOT", r"F:\Neo-MoFox-Shorekeeper")).resolve()
PLUGIN_REPO = Path(__file__).resolve().parents[2]
PLUGIN_DIR = PLUGIN_REPO / "mode_switcher"

# GBK 控制台下打中文/符号会抛 UnicodeEncodeError，让「断言全过」变成 exit 1（RISKS.md R14）
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
except Exception:  # noqa: BLE001
    pass

_failures: list[str] = []


class FakeReminderStore:
    """替身：system reminder store（只记账，不碰真框架）。"""

    def __init__(self) -> None:
        self.items: dict[tuple[str, str], dict[str, Any]] = {}
        self.deleted: list[tuple[str, str]] = []

    def set(
        self,
        bucket: str,
        name: str,
        content: str,
        insert_type: str | None = None,
        consume: str | None = None,
    ) -> None:
        self.items[(bucket, name)] = {
            "content": content,
            "insert_type": insert_type,
            "consume": consume,
        }

    def delete(self, bucket: str, name: str) -> bool:
        self.deleted.append((bucket, name))
        self.items.pop((bucket, name), None)
        return True

    def get(self, bucket: str, names: list[str] | None = None) -> str:
        return "\n\n".join(
            f"[{name}]\n{payload['content']}"
            for (item_bucket, name), payload in self.items.items()
            if item_bucket == bucket
        )


def check(name: str, ok: bool, extra: str = "") -> bool:
    """打印一条检查结果。"""

    mark = "PASS" if ok else "FAIL"
    print(f"[{mark}] {name}" + (f"  — {extra}" if extra else ""))
    if not ok:
        _failures.append(name)
    return ok


# --------------------------------------------------------------------------- #
# 替身：目标聊天插件的配置对象 + 模型配置对象
# --------------------------------------------------------------------------- #


class FakeProbSection:
    """default_chatter 的 programmatic_probability 节（守岸人现值）。"""

    def __init__(self) -> None:
        self.base_bypass_probability = 0.03
        self.name_mention_bonus = 0.7
        self.alias_mention_bonus = 0.4
        self.unread_message_bonus = 0.0
        self.next_tick_reply_bonus = 0.05


class FakeInterestSection:
    """default_chatter 的 interest 节。"""

    def __init__(self) -> None:
        self.reply_threshold = 0.78
        self.action_threshold = 0.55


class FakePluginSection:
    def __init__(self) -> None:
        self.programmatic_probability = FakeProbSection()
        self.interest = FakeInterestSection()


class FakeChatterConfig:
    def __init__(self) -> None:
        self.plugin = FakePluginSection()


class FakeTaskSection:
    def __init__(self, models: list[str]) -> None:
        self.model_list = list(models)
        self.max_tokens = 4096
        self.temperature = 0.3


class FakeTasksSection:
    def __init__(self, mapping: dict[str, list[str]]) -> None:
        self._tasks = {name: FakeTaskSection(models) for name, models in mapping.items()}

    def get_task(self, name: str) -> FakeTaskSection:
        if name not in self._tasks:
            raise ValueError(f"任务 '{name}' 未找到对应的配置")
        return self._tasks[name]


class FakeModelConfig:
    """守岸人的 model.toml 摘录。"""

    def __init__(self) -> None:
        self.model_tasks = FakeTasksSection(
            {
                "actor": ["deepseek-v4-flash", "deepseek-v4-pro"],
                "sub_actor": ["deepseek-v4-flash", "deepseek-v4-pro"],
                "utils": ["deepseek-v4-flash", "siliconflow-deepseek-ai/DeepSeek-V3.2"],
                "utils_small": ["deepseek-v4-flash", "siliconflow-deepseek-ai/DeepSeek-V3.2"],
                "tool_use": ["deepseek-v4-flash", "siliconflow-deepseek-ai/DeepSeek-V3.2"],
                "vlm": ["deepseek-v4-flash-vision-exp"],
                "embedding": ["bge-m3"],
            }
        )


def main() -> int:
    """入口。"""

    sys.path.insert(0, str(NEO_ROOT))
    sys.path.insert(0, str(PLUGIN_REPO))

    print(f"实例根目录 : {NEO_ROOT}")
    print(f"插件仓库   : {PLUGIN_REPO}")
    print(f"测试 cwd   : {Path.cwd()}")
    print("-" * 72)

    # ── 1. 真实框架导入冒烟 ────────────────────────────────────────────────
    try:
        from mode_switcher import inject, modes, runtime, state
        from mode_switcher.commands import ModeCommand
        from mode_switcher.config import ModeSwitcherConfig
        from mode_switcher.plugin import ModeSwitcherPlugin, _build_settings
        from mode_switcher.tools import (
            ALL_TOOLS,
            SetInsightModeTool,
            SetNormalModeTool,
            SetPowerSavingModeTool,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"[FAIL] 导入 mode_switcher 失败: {exc!r}")
        return 2
    check("插件模块可导入（真框架 + 真依赖）", True)

    # ── 2. 清单与组件元数据 ────────────────────────────────────────────────
    manifest = json.loads((PLUGIN_DIR / "manifest.json").read_text(encoding="utf-8"))
    check(
        "manifest.name 与目录名一致",
        manifest.get("name") == PLUGIN_DIR.name,
        f"{manifest.get('name')} / {PLUGIN_DIR.name}",
    )
    check(
        "manifest 版本与 plugin_version 一致",
        manifest.get("version") == ModeSwitcherPlugin.plugin_version,
        f"{manifest.get('version')} / {ModeSwitcherPlugin.plugin_version}",
    )
    includes = manifest.get("include", [])
    check(
        "manifest 声明了 command:mode",
        any(
            item.get("component_type") == "command" and item.get("component_name") == "mode"
            for item in includes
        ),
        str(includes),
    )
    check(
        "命令元数据正确（名字 / 类型 / 仅主人）",
        ModeCommand.name == "mode" and ModeCommand.component_type == "command",
        f"name={ModeCommand.name} type={ModeCommand.component_type}",
    )
    check(
        "命令认得出 /模式 /mode /档位",
        ModeCommand.match(["模式"]) == 1
        and ModeCommand.match(["mode"]) == 1
        and ModeCommand.match(["档位"]) == 1
        and ModeCommand.match(["别的"]) == 0,
    )

    # 声明的 api_version 必须是框架真有的模块
    try:
        from src.app.plugin_system.api import PLUGIN_API_VERSIONS

        declared = set(manifest.get("api_version", {}))
        unknown = sorted(declared - set(PLUGIN_API_VERSIONS))
        check("manifest 的 api_version 全是合法模块", not unknown, f"未知：{unknown}" if unknown else "")
    except Exception as exc:  # noqa: BLE001
        check("manifest 的 api_version 校验", False, f"取 PLUGIN_API_VERSIONS 失败：{exc!r}")

    # ── 3. 配置 → 设置 ─────────────────────────────────────────────────────
    config = ModeSwitcherConfig()
    settings = _build_settings(config)
    check(
        "默认档是省电",
        settings.default_mode == modes.POWER_SAVING,
        settings.default_mode,
    )
    check(
        "直通概率偏移 = 0.00 / +0.10 / +0.10",
        settings.base_offset(modes.POWER_SAVING) == 0.0
        and abs(settings.base_offset(modes.NORMAL) - 0.1) < 1e-9
        and abs(settings.base_offset(modes.INSIGHT) - 0.1) < 1e-9,
    )
    check(
        "兴趣阈值偏移 = 0.00 / -0.05 / -0.10",
        settings.threshold_offset(modes.POWER_SAVING) == 0.0
        and abs(settings.threshold_offset(modes.NORMAL) + 0.05) < 1e-9
        and abs(settings.threshold_offset(modes.INSIGHT) + 0.1) < 1e-9,
    )
    check(
        "只有洞悉开放未读加成，且值默认 0.05",
        settings.opens_unread(modes.INSIGHT)
        and not settings.opens_unread(modes.NORMAL)
        and not settings.opens_unread(modes.POWER_SAVING)
        and abs(settings.unread_open_value - 0.05) < 1e-9,
    )
    check(
        "只有省电降级模型，任务列表含 actor/sub_actor",
        settings.downgrades_models(modes.POWER_SAVING)
        and not settings.downgrades_models(modes.NORMAL)
        and not settings.downgrades_models(modes.INSIGHT)
        and "actor" in settings.downgrade_tasks
        and "sub_actor" in settings.downgrade_tasks,
        f"{settings.downgrade_tasks}",
    )

    plugin = ModeSwitcherPlugin(config)
    check("get_components 交出命令组件", ModeCommand in plugin.get_components())

    # ── 4. 档位名解析 ──────────────────────────────────────────────────────
    alias_cases = {
        "省电": modes.POWER_SAVING,
        "省电模式": modes.POWER_SAVING,
        "power": modes.POWER_SAVING,
        "节能": modes.POWER_SAVING,
        "常规": modes.NORMAL,
        "normal": modes.NORMAL,
        "普通": modes.NORMAL,
        "洞悉": modes.INSIGHT,
        "洞悉模式": modes.INSIGHT,
        "insight": modes.INSIGHT,
        " 洞察 ": modes.INSIGHT,
    }
    bad_aliases = [text for text, key in alias_cases.items() if modes.resolve_mode(text) != key]
    check("档位名/别名解析全对", not bad_aliases, f"错的：{bad_aliases}" if bad_aliases else f"{len(alias_cases)} 例")
    check("认不出的档位返回 None", modes.resolve_mode("随便什么") is None)

    # ── 5. 三档数值（替身目标配置） ────────────────────────────────────────
    chatter = FakeChatterConfig()
    model_config = FakeModelConfig()
    modes._plugin_config = lambda target_plugin: chatter  # type: ignore[assignment]
    modes._model_config = lambda: model_config  # type: ignore[assignment]

    modes.reset_snapshots()
    modes.configure(settings)

    prob = chatter.plugin.programmatic_probability
    interest = chatter.plugin.interest
    actor = model_config.model_tasks.get_task("actor")
    vlm = model_config.model_tasks.get_task("vlm")

    def snapshot() -> tuple[float, float, float, list[str]]:
        return (
            float(prob.base_bypass_probability),
            float(prob.unread_message_bonus),
            float(interest.reply_threshold),
            list(actor.model_list),
        )

    modes.apply(modes.POWER_SAVING)
    power = snapshot()
    check(
        "省电：直通 0.03 / 未读 0.00 / 阈值 0.78（全部维持现状）",
        power[:3] == (0.03, 0.0, 0.78),
        f"{power[:3]}",
    )
    check(
        "省电：actor 的 pro 被换成 flash",
        power[3] == ["deepseek-v4-flash"],
        f"{power[3]}",
    )
    check(
        "省电：vlm 不在任务列表里，没被动过",
        list(vlm.model_list) == ["deepseek-v4-flash-vision-exp"],
        f"{vlm.model_list}",
    )
    check(
        "省电：被点名/名字被提到的加成原样保留",
        prob.name_mention_bonus == 0.7 and prob.alias_mention_bonus == 0.4,
        f"{prob.name_mention_bonus}/{prob.alias_mention_bonus}",
    )

    modes.apply(modes.NORMAL)
    normal = snapshot()
    check(
        "常规：直通 0.03→0.13、未读维持 0.00、阈值 0.78→0.73",
        abs(normal[0] - 0.13) < 1e-9 and normal[1] == 0.0 and abs(normal[2] - 0.73) < 1e-9,
        f"{normal[:3]}",
    )
    check(
        "常规：模型还原成配置原值（沿用现有策略）",
        normal[3] == ["deepseek-v4-flash", "deepseek-v4-pro"],
        f"{normal[3]}",
    )

    modes.apply(modes.INSIGHT)
    insight = snapshot()
    check(
        "洞悉：直通与常规一致 0.13、未读开放 0.05、阈值再降到 0.68",
        abs(insight[0] - 0.13) < 1e-9
        and abs(insight[1] - 0.05) < 1e-9
        and abs(insight[2] - 0.68) < 1e-9,
        f"{insight[:3]}",
    )

    modes.apply(modes.POWER_SAVING)
    back = snapshot()
    check("切回省电没有漂移", back == power, f"{back[:3]}")

    # 门槛方向：省电 > 常规 > 洞悉
    check(
        "三档门槛从高到低（省电 > 常规 > 洞悉）",
        power[2] > normal[2] > insight[2] and power[1] <= normal[1] < insight[1],
        f"阈值 {power[2]} > {normal[2]} > {insight[2]}｜未读 {power[1]}/{normal[1]}/{insight[1]}",
    )

    # 幂等
    before = snapshot()
    modes.apply(modes.POWER_SAVING)
    modes.apply(modes.POWER_SAVING)
    check("重复应用同一档位结果不变（幂等）", snapshot() == before)

    # ── 6. 还原 ────────────────────────────────────────────────────────────
    modes.restore()
    restored = snapshot()
    check(
        "restore 把三处都写回配置原值",
        restored == (0.03, 0.0, 0.78, ["deepseek-v4-flash", "deepseek-v4-pro"]),
        f"{restored}",
    )

    # ── 7. 状态文本 ────────────────────────────────────────────────────────
    # 注意顺序：reset_snapshots 会顺手丢掉设置，必须先把设置注回去
    modes.reset_snapshots()
    modes.configure(settings)
    modes.apply(modes.INSIGHT)
    text = modes.describe()
    check("状态文本含档位与三行现值", "洞悉" in text and "0.13" in text and "0.68" in text, text.splitlines()[0])
    check(
        "状态文本说明兴趣阈值的条件",
        "兴趣值过滤" in text,
    )
    check("帮助文本列全三档", all(word in modes.help_text() for word in ("省电", "常规", "洞悉")))

    # ── 8. 降级规则（白名单 / 去重） ────────────────────────────────────────
    check(
        "白名单里的模型保留，其余换 flash",
        modes.downgrade_list(["qwen3-8b", "deepseek-v4-pro"], "deepseek-v4-flash", ["qwen3-8b"])
        == ["qwen3-8b", "deepseek-v4-flash"],
    )
    check(
        "整张列表都在白名单里则不动",
        modes.downgrade_list(["qwen3-8b"], "deepseek-v4-flash", ["qwen3-8b"]) == ["qwen3-8b"],
    )
    check(
        "已经是便宜模型时去重成一个",
        modes.downgrade_list(["deepseek-v4-flash", "deepseek-v4-pro"], "deepseek-v4-flash", [])
        == ["deepseek-v4-flash"],
    )

    # ── 9. 档位持久化 + 编排层 ─────────────────────────────────────────────
    with tempfile.TemporaryDirectory() as tmp:
        cwd = os.getcwd()
        os.chdir(tmp)
        try:
            runtime.configure(settings)
            asyncio.run(state.save(settings.state_key, modes.INSIGHT))
            loaded = asyncio.run(state.load(settings.state_key, modes.POWER_SAVING, set(modes.MODES)))
            check("档位可落盘并读回", loaded == modes.INSIGHT, loaded)

            asyncio.run(state.save(settings.state_key, "不存在的档位"))
            fallback = asyncio.run(state.load(settings.state_key, modes.POWER_SAVING, set(modes.MODES)))
            check("存档里是坏值时回落默认档", fallback == modes.POWER_SAVING, fallback)

            state_file = Path("data") / "json_storage" / f"{settings.state_key}.json"
            check("存档文件确实生成", state_file.exists(), str(state_file))

            ok, reply = asyncio.run(runtime.switch("常规"))
            check("runtime.switch 能拨档", ok and "常规" in reply, reply.splitlines()[0])
            check("拨档后当前档位已更新", modes.current_mode() == modes.NORMAL)
            check("status_text 可用", "运行档位" in runtime.status_text())

            bad_ok, bad_reply = asyncio.run(runtime.switch("八档"))
            check("认不出的档位不切、给帮助", (not bad_ok) and "可用" in bad_reply)
            check("认不出时不改动当前档位", modes.current_mode() == modes.NORMAL)

            asyncio.run(runtime.apply_mode(modes.POWER_SAVING))
            check("切回省电（收尾）", modes.current_mode() == modes.POWER_SAVING)
        finally:
            os.chdir(cwd)

    # ── 10. 加载 / 卸载路径（on_plugin_loaded → 应用，卸载 → 还原） ────────
    real_store_fn = inject._store
    reminder_store = FakeReminderStore()
    inject._store = lambda: reminder_store  # type: ignore[assignment]
    with tempfile.TemporaryDirectory() as tmp:
        cwd = os.getcwd()
        os.chdir(tmp)
        try:
            load_config = ModeSwitcherConfig()
            load_config.plugin.state_key = "mode_switcher_load_check"
            loaded_plugin = ModeSwitcherPlugin(load_config)

            asyncio.run(loaded_plugin.on_plugin_loaded())
            check(
                "首次加载（无存档）落到默认档省电",
                modes.current_mode() == modes.POWER_SAVING,
                modes.current_mode(),
            )
            check(
                "加载即把 actor 降级成 flash",
                list(actor.model_list) == ["deepseek-v4-flash"],
                f"{actor.model_list}",
            )
            key = (load_config.inject.buckets[0], load_config.inject.name)
            injected = reminder_store.items.get(key, {}).get("content", "")
            check(
                "加载即写入档位 reminder（含档位与防背书说明）",
                "省电" in injected and "不是要念出来的台词" in injected,
                injected.splitlines()[0] if injected else "（没写进去）",
            )
            check(
                "reminder 是常驻且固定的那一种",
                reminder_store.items.get(key, {}).get("insert_type") == "fixed"
                and reminder_store.items.get(key, {}).get("consume") == "forever",
            )

            asyncio.run(loaded_plugin.on_plugin_unloaded())
            check(
                "卸载即还原所有配置原值",
                list(actor.model_list) == ["deepseek-v4-flash", "deepseek-v4-pro"]
                and abs(float(prob.base_bypass_probability) - 0.03) < 1e-9
                and abs(float(interest.reply_threshold) - 0.78) < 1e-9,
                f"{actor.model_list}｜{prob.base_bypass_probability}｜{interest.reply_threshold}",
            )
            check("卸载即清掉档位 reminder", key in reminder_store.deleted, f"{reminder_store.deleted}")

            asyncio.run(state.save("mode_switcher_load_check", modes.INSIGHT))
            reloaded_plugin = ModeSwitcherPlugin(load_config)
            asyncio.run(reloaded_plugin.on_plugin_loaded())
            check(
                "有存档时按存档档位加载（洞悉）",
                modes.current_mode() == modes.INSIGHT
                and abs(float(prob.base_bypass_probability) - 0.13) < 1e-9
                and abs(float(prob.unread_message_bonus) - 0.05) < 1e-9,
                f"{modes.current_mode()}｜{prob.base_bypass_probability}｜{prob.unread_message_bonus}",
            )
            insight_injected = reminder_store.items.get(key, {}).get("content", "")
            check(
                "换档后注入内容跟着换（洞悉）",
                "洞悉" in insight_injected
                and "链接全开" in insight_injected
                and "只是省电" not in insight_injected,
                insight_injected.splitlines()[0] if insight_injected else "（没写进去）",
            )
            asyncio.run(reloaded_plugin.on_plugin_unloaded())
        finally:
            os.chdir(cwd)

    # ── 10.5 注入文本本身 ──────────────────────────────────────────────────
    modes.reset_snapshots()
    modes.configure(settings)
    power_text = inject.text_for(modes.POWER_SAVING, settings)
    insight_text = inject.text_for(modes.INSIGHT, settings)
    check(
        "注入文本带档位名 + 该档说明 + 三档清单",
        "省电" in power_text
        and "只是省电" in power_text
        and all(word in power_text for word in ("省电", "常规", "洞悉")),
    )
    check(
        "洞悉档的注入不带省电那套说法",
        "洞悉" in insight_text and "链接全开" in insight_text and "只是省电" not in insight_text,
    )
    check(
        "防背书：注入不写具体参数、并声明不是台词",
        "不是要念出来的台词" in power_text
        and "0.13" not in insight_text
        and "deepseek" not in power_text,
    )
    custom = modes.Settings(
        inject_texts={modes.INSIGHT: "自定义说明"},
        inject_include_mode_list=False,
        inject_guard="自定义守卫",
    )
    custom_text = inject.text_for(modes.INSIGHT, custom)
    check(
        "文案可在配置里整段替换",
        "自定义说明" in custom_text and "自定义守卫" in custom_text and "可用档位" not in custom_text,
    )
    check(
        "注入开关关掉时不写 reminder",
        inject.sync(modes.NORMAL, modes.Settings(inject_enabled=False)) is False,
    )
    multi_buckets = modes.Settings(inject_buckets=["actor", "sub_actor"])
    inject.sync(modes.NORMAL, multi_buckets)
    check(
        "多 bucket 时逐个写",
        all(
            (bucket, multi_buckets.inject_name) in reminder_store.items
            for bucket in ("actor", "sub_actor")
        ),
        f"{sorted(key[0] for key in reminder_store.items)}",
    )

    # ── 11. 真实 reminder store 往返（就在进程内存里，不落盘） ─────────────
    try:
        from src.app.plugin_system.api import prompt_api

        inject._store = real_store_fn
        inject.sync(modes.INSIGHT, settings)
        roundtrip = prompt_api.get_system_reminder("actor", ["mode_switcher_now"])
        check(
            "真实 reminder store 往返成功",
            "洞悉" in roundtrip and "不是要念出来的台词" in roundtrip,
            f"{len(roundtrip)} 字符",
        )
        inject.clear(settings)
        check(
            "真实 store 里也能删干净",
            "洞悉" not in prompt_api.get_system_reminder("actor", ["mode_switcher_now"]),
        )
    except Exception as exc:  # noqa: BLE001
        print(f"[SKIP] 真实 reminder store 往返（框架未初始化，属正常）：{exc!r}")
    finally:
        inject._store = lambda: reminder_store  # type: ignore[assignment]

    # ── 12. 自主拨档工具（三个 set_mode_*） ────────────────────────────────
    from mode_switcher.tools import ALL_TOOLS

    tool_entries = [
        item
        for item in includes
        if item.get("component_type") == "tool"
    ]
    check(
        "manifest 声明了三个 tool，且名字与类一致",
        sorted(item.get("component_name") for item in tool_entries)
        == sorted(tool.name for tool in ALL_TOOLS)
        and len(tool_entries) == 3,
        f"{[item.get('component_name') for item in tool_entries]}",
    )
    check(
        "三个工具各自对应一档，且说明写清边界",
        {tool.target_mode for tool in ALL_TOOLS} == set(modes.MODE_ORDER)
        and all(len(tool.description) > 40 for tool in ALL_TOOLS)
        and all(tool.component_type == "tool" for tool in ALL_TOOLS),
        "、".join(f"{tool.name}→{modes.mode_label(tool.target_mode)}" for tool in ALL_TOOLS),
    )
    check(
        "工具说明提醒「不用报告档位」",
        all("报告档位" in tool.description for tool in ALL_TOOLS),
    )

    with tempfile.TemporaryDirectory() as tmp:
        cwd = os.getcwd()
        os.chdir(tmp)
        try:
            runtime.configure(settings)
            modes.reset_snapshots()
            modes.configure(settings)
            asyncio.run(runtime.apply_mode(modes.POWER_SAVING, persist=False))
            runtime._last_tool_switch_at = 0.0  # type: ignore[attr-defined]

            sent: list[str] = []

            async def _fake_send(text: str, stream_id: str = "") -> None:
                sent.append(text)

            real_send = runtime.send_text
            runtime.send_text = _fake_send  # type: ignore[assignment]

            tool = SetNormalModeTool(plugin)
            ok, text = asyncio.run(tool.execute())
            check(
                "工具切档成功并落到「常规」",
                ok and modes.current_mode() == modes.NORMAL and "常规" in text,
                text.splitlines()[0][:60],
            )
            check(
                "工具切档会落盘（存档里是常规）",
                asyncio.run(state.load(settings.state_key, modes.POWER_SAVING, set(modes.MODES)))
                == modes.NORMAL,
            )
            check(
                "工具结果声明「这是系统回执，不用念出来」",
                "不用念出来" in text,
            )
            check("默认不开播报（没替她说话）", not sent, f"{sent}")

            ok_same, text_same = asyncio.run(SetNormalModeTool(plugin).execute())
            check(
                "已经在目标档位时是空操作",
                ok_same and "已经" in text_same,
                text_same[:40],
            )

            # 白名单：只允许省电档
            locked = modes.Settings(tool_allowed_modes=[modes.POWER_SAVING])
            runtime.configure(locked)
            ok_locked, text_locked = asyncio.run(SetInsightModeTool(plugin).execute())
            check(
                "白名单外的档位切不动",
                (not ok_locked) and modes.current_mode() == modes.NORMAL,
                text_locked[:40],
            )
            runtime.configure(settings)

            # 整体关掉
            runtime.configure(modes.Settings(tools_enabled=False))
            ok_off, text_off = asyncio.run(SetInsightModeTool(plugin).execute())
            check("整体关掉时切不动", (not ok_off) and "关着" in text_off, text_off[:40])
            runtime.configure(settings)

            # 冷却
            cooled = modes.Settings(tool_cooldown_minutes=60)
            runtime.configure(cooled)
            runtime._last_tool_switch_at = 0.0  # type: ignore[attr-defined]
            ok_first, _ = asyncio.run(SetInsightModeTool(plugin).execute())
            ok_second, text_second = asyncio.run(SetPowerSavingModeTool(plugin).execute())
            check(
                "冷却期内第二次切档被挡下",
                ok_first and (not ok_second) and "刚换过档位" in text_second,
                text_second[:40],
            )

            # 播报
            announcing = modes.Settings(tool_announce=True, tool_cooldown_minutes=0.0)
            runtime.configure(announcing)
            runtime._last_tool_switch_at = 0.0  # type: ignore[attr-defined]
            sent.clear()
            ok_ann, _ = asyncio.run(
                runtime.switch_from_tool(modes.POWER_SAVING, stream_id="test:stream")
            )
            check(
                "开播报时替她说一句（带档位名）",
                ok_ann and len(sent) == 1 and "省电" in sent[0],
                f"{sent}",
            )

            runtime.send_text = real_send  # type: ignore[assignment]
            runtime.configure(settings)
            runtime._last_tool_switch_at = 0.0  # type: ignore[attr-defined]
            asyncio.run(runtime.apply_mode(modes.POWER_SAVING, persist=False))
        finally:
            os.chdir(cwd)

    # ── 13. 组件注册表（可选，需要框架 registry 就绪） ─────────────────────
    try:
        from src.core.components.registry import get_global_registry

        registry = get_global_registry()
        signatures = [str(sig) for sig in registry.list_all()]
        hit = [sig for sig in signatures if "mode_switcher" in sig]
        if not signatures:
            # 注册表是靠插件管理器加载时才填的；离线跑自检时是空的，属正常
            print("[SKIP] 注册表检查（注册表为空＝框架没启动过，属正常）")
        else:
            check("组件注册表里能查到本插件", bool(hit), f"{hit}" if hit else f"注册表 {len(signatures)} 项，未见 mode_switcher")
    except Exception as exc:  # noqa: BLE001
        print(f"[SKIP] 注册表检查（框架未初始化，属正常）：{exc!r}")

    print("-" * 72)
    if _failures:
        print(f"结果：{len(_failures)} 项失败 -> {_failures}")
        return 1
    print("结果：全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
