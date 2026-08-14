# Flutter

本领域预留给可复用的 Flutter 跨层知识。目前不是建设重点，尚无专题正文。

## 规划边界

| 主题 | 预留路径 | 范围 |
| --- | --- | --- |
| Flutter Framework | `framework/` | Widget、Element、RenderObject、布局、绘制与状态更新 |
| Flutter Engine | `engine/` | Dart Runtime、线程模型、帧管线、平台与渲染接口 |
| Android Embedding | `embedding/android/` | Activity、View、Engine 生命周期、JNI、插件与 Platform Channel |
| Rendering | `rendering/` | Flutter 渲染架构及其与平台图形栈的关系 |
| Skia | `rendering/skia/` | Skia 的职责、接入边界和历史版本关系 |
| Impeller | `rendering/impeller/` | Impeller 架构、着色器、后端及性能验证 |

这些路径只是导航约定，并不代表目录或事实源已经存在。开始某一主题时，再创建包含实际范围、内容和证据的专题入口。

## 与 Android 的关系

Flutter 在 Android 上的启动、生命周期、Surface、输入和显示最终依赖 Android 平台机制。相关系统侧知识由 [Android 领域](../android/README.md)维护；Flutter 文档只解释 Flutter 自己的实现及两者交界，不复制 Android 正文。

具体 Flutter 项目的架构和运行状态不属于本仓库，应由对应项目自己的事实源维护。
