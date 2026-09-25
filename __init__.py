"""mode_switcher 插件包：三档模式（省电 / 常规 / 洞悉）。

插件入口在 :mod:`plugin` 模块中由 ``@register_plugin`` 装饰的
``ModeSwitcherPlugin`` 类注册，由插件加载器自动发现——因此这里**不要**导入
``plugin`` 里的东西：加载器是以 ``mode_switcher.plugin`` 为名执行的，包内再做
``from .plugin import ...`` 会变成循环导入（父包初始化时入口模块还没执行完）。

本包职责：

- :mod:`modes` —— 三档的定义，以及「一个档位 = 改哪些内存配置」的纯逻辑；
- :mod:`state` —— 当前档位的持久化（``data/json_storage/<state_key>.json``）；
- :mod:`runtime` —— 编排：读档、应用、生成状态文本（命令与插件入口共用）；
- :mod:`commands` —— ``/模式`` 命令（查看 / 切换）；
- :mod:`config` —— 插件配置（偏移量、目标插件、降级模型与任务列表）。
"""

__all__: list[str] = []
