# Flutter Scene 与 Lantern Spirit 案例

本专题集中维护 Flutter Scene 库的底层渲染机制，以及以 Lantern Spirit 固定开源源码为案例的动画、坐标转换、转场与触摸反馈。这里的 Flutter Scene 指案例使用的场景库；各文的版本基线与适用边界由正文和证据包维护。

## 阅读顺序

1. [Flutter Scene 的底层实现与性能边界](Flutter-Scene底层实现与性能边界.md)：渲染分层、命令与资源、线程交界和测量口径；固定来源见 [对应证据包](../../../evidence/flutter/scene/scene-internals-performance/manifest.json)。
2. [Flutter Scene 的动画与交互叠加](Flutter-Scene动画与交互叠加.md)：资源准备、节点层级、动画混合、交互变换与面部形变；固定来源见 [对应证据包](../../../evidence/flutter/scene/scene-animation-composition/manifest.json)。
3. [Flutter Scene 的坐标转换与射线拾取](Flutter-Scene坐标转换与射线拾取.md)：屏幕与世界坐标、投影与逆投影、求交约束及局部命中；固定来源见 [对应证据包](../../../evidence/flutter/scene/scene-coordinate-picking/manifest.json)。

以下两篇可按交互效果独立阅读：

- [Flutter 触摸粒子反馈与爱心动效](Flutter-触摸粒子反馈与爱心动效.md)：输入与发射节奏、运动模拟、画笔表现、角色联动及重绘边界；固定来源见 [对应证据包](../../../evidence/flutter/scene/touch-particle-feedback/manifest.json)。
- [Flutter 裁剪展开转场与性能边界](Flutter-裁剪展开转场与性能边界.md)：页面布局、窗口裁剪、场景渲染和同场景展开；固定来源见 [对应证据包](../../../evidence/flutter/scene/clipped-reveal-transitions/manifest.json)。

## 范围与维护边界

底层渲染、动画叠加、坐标拾取、页面转场与触摸粒子分别作为独立事实源维护。相关插图放在本专题的 `assets/` 下，证据包放在对应的 `evidence/flutter/scene/` 下；本文只维护阅读入口。

案例用于解释可复用机制，不维护 Lantern Spirit 的功能清单、架构现状、运行配置或任务计划。新增内容按机制归入现有文档；形成独立阅读或验证单元时再拆分。

原生视图与系统合成的交界见 [Rendering 专题](../rendering/README.md)。线程调度的前置知识见 [线程模型与性能同步](../engine/线程模型与性能同步.md)，设备性能的取证方法见 [运行时性能验证链](../engine/运行时性能验证链.md)；具体运行证据仍由对应项目保存。
