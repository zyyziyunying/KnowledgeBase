# Flutter Rendering

本专题维护 Flutter 绘制结果如何与原生图形内容组合、场景图中的动画与交互机制，以及 Framework、Engine、平台视图和系统合成器之间的接口。线程调度的通用模型由 [Engine 专题](../engine/README.md)维护。

## 阅读顺序

1. [线程模型与性能同步](../engine/线程模型与性能同步.md)：先区分 UI、platform、raster 的执行归属与同步边界。
2. [Android Platform Views 与原生渲染](Android-Platform-Views与原生渲染.md)：原生控件与外部纹理的选择，VD、TLHC、HC、HCPP 的合成路径，以及创建、交互与验证边界。
3. [对应证据包](../../../evidence/flutter/rendering/android-platform-views/manifest.json)：固定源码版本、哈希、断言和官方文档元数据。

场景图方向可独立阅读 [Flutter Scene 的动画与交互叠加](Flutter-Scene动画与交互叠加.md)：从资源准备与逐帧更新进入节点层级、动画混合、交互变换与面部形变；固定来源见 [对应证据包](../../../evidence/flutter/rendering/scene-animation-composition/manifest.json)。

坐标转换方向可继续阅读 [Flutter Scene 的坐标转换与射线拾取](Flutter-Scene坐标转换与射线拾取.md)：屏幕与世界坐标、投影与逆投影、求交约束及局部命中；固定来源见 [对应证据包](../../../evidence/flutter/rendering/scene-coordinate-picking/manifest.json)。

页面与场景的转场可独立阅读 [Flutter 裁剪展开转场与性能边界](Flutter-裁剪展开转场与性能边界.md)：区分页面布局、窗口裁剪、场景渲染和同场景展开；固定来源见 [对应证据包](../../../evidence/flutter/rendering/clipped-reveal-transitions/manifest.json)。

触摸粒子方向可独立阅读 [Flutter 触摸粒子反馈与爱心动效](Flutter-触摸粒子反馈与爱心动效.md)：从输入与发射节奏进入运动模拟、画笔表现、角色联动及重绘边界；固定来源见 [对应证据包](../../../evidence/flutter/rendering/touch-particle-feedback/manifest.json)。

## 范围与拆分边界

Android 原生内容集成、场景图动画、坐标转换与拾取、页面转场与触摸粒子各自作为独立阅读单元。场景图、坐标转换、转场与粒子内容使用固定开源案例解释可复用机制，不维护案例应用的架构或运行状态。iOS 只记录平台差异入口，不在这里展开 UIKit 合成实现。后续 Layer tree、Skia、Impeller 后端与资源管理形成独立内容时，再建立相应事实源；不把它们持续堆入 Platform Views 文档。

Android 的 Surface、BufferQueue、SurfaceFlinger 和 HWC 机制归入 [Android 领域](../../android/README.md)。涉及 Android 图形栈时，本专题只解释 Flutter 与这些机制的交界；不保存具体应用、设备、trace 或一次运行的性能结论。
