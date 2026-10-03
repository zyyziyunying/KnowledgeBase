# Flutter

本领域维护可复用的 Flutter 跨层知识。当前从 Android 上“输入到路由首帧”的链路开始建设；具体应用、设备和一次实测的结论仍应保留在对应项目的事实源中。

## 专题

| 专题 | 状态 | 入口 |
| --- | --- | --- |
| Flutter Engine | 已开始；先维护线程模型与性能同步，再维护 Android 输入、UI/raster、帧调度与首帧诊断的交界 | [Engine](engine/README.md) |
| Flutter Rendering | 原生视图、外部纹理与系统合成的交界 | [Rendering](rendering/README.md) |
| Flutter 建设路线 | 当前建设顺序、延期项与完成标准 | [ROADMAP.md](ROADMAP.md) |

## 规划边界

| 主题 | 预留路径 | 范围 |
| --- | --- | --- |
| Flutter Framework | `framework/` | Widget、Element、RenderObject、布局、绘制与状态更新 |
| Flutter Engine | `engine/` | Dart Runtime、线程模型、帧管线、平台与渲染接口 |
| Android Embedding | `embedding/android/` | Activity、View、Engine 生命周期、JNI、插件与 Platform Channel |
| Rendering | `rendering/` | Flutter 渲染架构及其与平台图形栈的关系 |
| Skia | `rendering/skia/` | Skia 的职责、接入边界和历史版本关系 |
| Impeller | `rendering/impeller/` | Impeller 架构、着色器、后端及性能验证 |

Engine 与 Rendering 已有专题入口；其余路径只是导航约定，并不代表目录或事实源已经存在。开始某一主题时，再创建包含实际范围、内容和证据的专题入口。

## 与 Android 的关系

Flutter 在 Android 上的启动、生命周期、Surface、输入和显示最终依赖 Android 平台机制。相关系统侧知识由 [Android 领域](../android/README.md)维护；Flutter 文档只解释 Flutter 自己的实现及两者交界，不复制 Android 正文。

具体 Flutter 项目的架构和运行状态不属于本仓库，应由对应项目自己的事实源维护。
