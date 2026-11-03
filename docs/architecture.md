# 工程结构与模块边界

项目沿用 Python 标准库与 Tkinter/ttk。新增功能按功能包组织，界面、业务流程和系统访问分别维护。

## 当前结构

```text
大文件扫描器.py          启动、主窗口、页面注册、跨页导航；仍包含原有文件浏览及大文件扫描实现
ui_theme.py             统一配色、字体和控件样式
app_storage/
  __init__.py           应用空间统计的公开后端接口
  common.py             取消信号与路径片段校验
  models.py             应用、关联目录、测量结果和用量快照
  discovery.py          应用枚举、Spotlight 补充、应用标识和签名信息读取
  association.py        外部数据匹配、共享归属、父子目录去重
  measurement.py        可取消的目录空间测量与读取异常记录
  service.py            扫描流程、并发任务调度、结果事件交付
  presentation.py       用量及异常状态的显示文本转换
  view.py               磁盘清理页控件、交互与主线程结果队列处理
tests/                  业务回归测试与独立原生验证工具
trash_helper.swift      macOS 原生废纸篓操作
大文件扫描器.spec        构建入口与原生辅助程序打包
```

## 依赖方向

- 主窗口创建 `AppStoragePage`，通过回调提供访达打开和跨页浏览能力。
- 页面调用 `service`，使用 `models` 与 `presentation` 展示结果。
- `service` 组合 `discovery`、`association`、`measurement`，通过事件回调交付结果，不导入 Tkinter。
- 底层模块依赖数据模型和公共校验，不访问主窗口或页面对象。
- 数据模型与显示文本转换可以独立测试，无需启动图形窗口。

## 后续开发约定

- 新增业务功能建立职责清晰的模块或功能包，主窗口负责接入与导航。
- 后台任务通过队列交付数据，Tk 控件只在主线程更新。
- 平台命令、文件读写、配置持久化应有清晰边界，业务计算保持可独立测试。
- 测试针对实际行为；拆分模块时同步调整测试依赖入口，保留原有回归覆盖。
- 文件浏览、大文件扫描和设置等已有职责，在相关功能维护时逐步从主文件提取。
- 代码移动保持行为一致，功能变更单独描述和验证。

验证命令：`.venv/bin/python -m unittest discover -s tests`。构建继续使用原有 `.spec`，PyInstaller 会沿静态导入收集功能包。
