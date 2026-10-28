# Flutter Scene 的动画与交互叠加

预制动画与交互动作可以分别控制父子节点，再通过场景图的矩阵乘法组合。动画系统写主姿态，交互逻辑写局部偏移，网格与材质负责外形和表情。理解这三个层次后，就能追踪一个角色如何同时播放动作、看向手指、发生局部形变。

本文以作者公开的 Lantern Spirit 源码作为固定教学案例，沉淀节点变换、动画混合与逐帧更新机制；不维护该应用的功能清单、架构现状、运行配置或任务计划。示例聚焦默认角色 Lumi 留在页面头部区域的常规路径，其他角色和全屏外出路径不直接套用这里的局部尺寸或调用链。

## 源码基线与阅读入口

| 来源 | 固定 revision | 用途 |
| --- | --- | --- |
| [bdero/lantern_spirit][app-repo] | `bc151089f4ecfeae6675ef98731b55f8770ed39b` | 节点生成、角色控制、页面更新与材质 |
| [bdero/flutter_scene][scene-repo] | `b8023c6261ed77ed4046d72c86496ed40c96b37b` | 节点矩阵、动画播放器、SceneView 与场景更新 |

核对日期：2026-10-28。第二个 revision 由案例的 [pubspec.yaml][dependency] 固定；Flutter Scene 是本例使用的库，其 API 与动画混合实现不能直接视为 Flutter SDK 的通用保证。证据入口：[manifest.json](../../../evidence/flutter/scene/scene-animation-composition/manifest.json)。下文 claim ID 对应其中的映射。

## 从资源准备到每帧绘制

先区分三个职责：Flutter 页面组织布局与输入；`Scene` 容纳 3D 节点并执行场景更新和渲染；角色控制器维护动作状态、交互偏移、表情与材质参数。相机决定观察场景的视角。

固定案例的入口可按以下顺序阅读：

```text
main 读取 Profile
  → LanternSpiritApp 展示 Boot
  → 加载资源并预热场景管线
  → ParkScreen 创建角色
  → SceneView 驱动更新与重绘
```

资源加载与渲染预热是不同步骤。`Preload.run()` 先加载模型、材质、图集、声音等资源，再构造用于预热的场景并调用 `warmUp()`；这是提前承担首次资源与管线准备成本的机制，实际延迟收益需要测量。角色加载再把模型、材质和表情图集组装起来，通过 `_bind()` 绑定节点与动画，最后加入场景。[入口][app-main]、[加载页][boot]、[预加载][preload]、[角色加载][character]。对应证据：`scene-animation-001`。

常规头部路径的逐帧关系如下：

```text
SceneView 的 Ticker
  → 页面回调整理滚动、注意力与角色反应
  → character.update 更新权重、交互姿态、表情和几何体
  → scene.update 推进动画播放器和场景更新
  → 通知重绘
  → CustomPainter.paint 调用 scene.render
```

`appSceneView()` 先调用页面传入的 `onTick`，再调用 `scene.update(dt)`。库中的 `SceneView` 在回调返回后通知重绘；显式更新过场景后，渲染阶段跳过当帧隐式 tick。[页面回调][park]、[应用封装][app-clock]、[SceneView][scene-view]、[场景更新][scene-update]。对应证据：`scene-animation-002`。

这里描述的是更新到绘制的代码关系，不代表屏幕已呈现。另一个时间边界是：`character.update()` 把内部 `dt` 限制在 `[0, 1/20]` 秒，而封装传给 `scene.update()` 的仍是原始 `dt`；大时间步下不能认为交互模拟与动画片段始终推进相同的时长。

## 用父子节点分配变换的写入者

生成器为头部建立下面的结构，省略其他身体部位及上层导入节点：

```text
Lantern
└── HeadCtrl
    └── HeadFx
        ├── Head
        └── Face
```

| 节点 | 主要写入者 | 职责 |
| --- | --- | --- |
| `HeadCtrl` | 动画播放器 | 接收片段混合后的平移、旋转与缩放，包含头部基础位置 |
| `HeadFx` | Dart 交互逻辑 | 在主姿态之内增加浮动、转头、整体压扁等局部变换 |
| `Head` | 几何体装配与外形逻辑 | 头部网格及其局部尺寸 |
| `Face` | 面部几何体、局部变换与材质逻辑 | 面部薄壳、表情及拆解视图偏移 |

`HeadCtrl` 与 `HeadFx` 不挂 mesh，可理解为两个嵌套坐标系。`Head` 和 `Face` 是兄弟节点，两者共同继承上层姿态；面部仍能拥有自己的材质和局部变换。

生成器先收集 `Head` 与 `Face` 为同一组子节点，再生成 `HeadFx`，最后将它放入 `HeadCtrl`。动画通道的目标使用 `ctrl[part]`，所以动作函数返回字典中的 `"Head"` 最终对应 `HeadCtrl`，而不是同名网格节点。[生成器][rig]。对应证据：`scene-animation-003`。

## 预制动画写主姿态

案例用 Python 函数描述动作，再将采样值写入 GLB。`Awake` 的头部平移为 `(0, 1.8, 0) + (0, 0.04 × sin(w), 0)`，同时包含轻微旋转和缩放。生成器以每秒 30 个采样间隔记录各部位的 translation、rotation、scale，并声明 `LINEAR` 插值。这个数字是资源采样率，不是应用渲染帧率。

运行时角色为各状态创建 clip，用权重控制过渡。多个片段先由动画播放器合成，结果写入 `HeadCtrl`；交互层仍有自己的 `HeadFx`。[生成器][rig]、[角色权重][character]、[动画播放器][player]。对应证据：`scene-animation-004`。

```text
Sleepy clip ──┐
              ├─ 按片段权重处理 ──→ HeadCtrl
Awake clip ───┘

交互目标与弹簧状态 ── 每帧计算 ──→ HeadFx
```

片段之间的混合与父子节点的组合是两个步骤。在固定库版本中，播放器先恢复绑定姿态，再应用片段；平移累加相对绑定姿态的加权差，旋转依次执行 slerp，缩放按相对绑定姿态的比例因子相乘。不要将其概括为两个完整矩阵的线性加权，也不要把这个版本的具体算法推广到其他动画库。[属性解析器][resolver]

## 交互逻辑写局部偏移

角色的 `_bind()` 按名字取得 `HeadFx`。随后 `_updateMotion()` 每帧重建其局部矩阵；等价的结构简写如下，变量名为解释用途：

```dart
headFx.localTransform = Matrix4.compose(
  Vector3(0, bob + hop + explodeOffset, 0),
  yawRotation * pitchRotation,
  Vector3(scaleX, scaleY, scaleZ),
);
```

平移包含浮动弹簧、跳动和拆解视图偏移；旋转来自注视目标；缩放包含整体压扁与拉伸。每帧由当前状态重新构造矩阵，避免把同一偏移不断累积到上一帧矩阵上。[交互变换][character]。对应证据：`scene-animation-005`。

注视目标也不是直接跳到终点。实现分别平滑面部视线状态和头部朝向，形式为 `current += (target - current) × (1 - exp(-dt × k))`：视线的 `k = 28`，头部的 `k = 5.5`。若教学假设 `dt = 1/60` 秒，每步分别消除约 37.3% 和 8.8% 的剩余差距，因此视线更快、头部稍后跟上。没有显式跟随目标时，头部目标还可能被缩小为视线目标的 0.45 倍。

`_look` 进入头部旋转，`_eyes` 进入面部材质的 UV 偏移。这里的“眼睛移动”是视觉描述：shader 实际对采样整张表情图案的 UV 做偏移，并没有独立旋转眼球网格。[面部材质][face]

## 矩阵相乘怎样叠加动作

Flutter Scene 的节点世界矩阵由父节点世界矩阵乘本节点局部矩阵得到。采用列向量记法，把顶点记为 `p`，头部的组合为：

```text
p_world = M_ancestors × M_HeadCtrl × M_HeadFx × M_Head × p
```

矩阵作用于顶点时从右向左理解：网格先获得局部尺寸，再进入交互坐标系，再进入动画主姿态，最后进入上层世界空间。面部使用同一段祖先链，只将末端 `M_Head` 换成 `M_Face`。[节点世界变换][node]。对应证据：`scene-animation-006`。

教学例子：假设上层矩阵为单位矩阵，`HeadCtrl` 只有 `(0, 1.8, 0)` 的平移，`HeadFx` 由向上 0.1 的平移和绕 Y 轴转头组成，`Head` 是以原点为中心、缩放到半径 0.62 的球。此时头中心为 `(0, 1.9, 0)`，球体同时带有交互转头。

直接相加高度只适用于这个简化条件。若 `HeadCtrl` 带有旋转或缩放，`HeadFx` 的位移向量也会被它旋转或缩放；局部“向上”未必是世界空间竖直向上。矩阵一般不可交换，节点层级的顺序不能随意对调。

本例的调用顺序先写 `HeadFx`，随后动画系统写 `HeadCtrl`，两者不会覆盖同一个局部矩阵。最终乘法顺序由父子关系决定。这个结论不意味着所有逐帧逻辑都可任意重排：在 `scene.update()` 之前读取动画节点的世界坐标，不会自动提前采样尚未推进的动画片段。

## 面部跟随包含变换和形变两个层次

共同父节点让 `Head` 和 `Face` 一起浮动、转头及整体缩放。两者的尺寸表达却不同：生成器中的头部是单位球网格加节点缩放 `0.62`，面部薄壳顶点直接位于半径 `0.62 × 1.012 = 0.62744` 的表面附近。因此不能因为它们一起运动，就把现有 `Face` 原样改挂到带缩放的 `Head` 下，否则会额外继承一次缩放。[球体与薄壳生成][rig]。对应证据：`scene-animation-007`。

局部凹陷需要更新顶点。角色绑定时将头部与薄壳替换为 `SoftHead` 提供的可变形几何体；软体使用同一套 12 个控制点的偏移，按各顶点的方向权重，分别生成头部和面部顶点。头部输出处于单位球局部空间，薄壳输出乘以 `radius × capScale`，两组结果分别重建各自几何体。[角色装配][character]、[软体写入][soft]

这些机制共同形成可见动作：

| 可见变化 | 控制机制 |
| --- | --- |
| 清醒状态的周期浮动和摆动 | 动画片段 → `HeadCtrl` |
| 朝手指转头和整体弹动 | 交互状态 → `HeadFx` |
| 手指附近的局部凹陷 | 软体控制点 → 头部与面部顶点 |
| 表情切换和视线偏移 | `Face` 材质的图集采样、混合与 UV 偏移 |

表情 shader 从图集采样前后两张表情，再按 `frame_mix` 混合。它与节点姿态、几何体形变有独立的输入，因此可以在转头和捏脸时继续切换表情。[面部材质][face]。对应证据：`scene-animation-008`。

## 适用边界与后续阅读

以上是固定源码中的机制与数学关系，尚未验证具体设备上的运行画面、帧率、输入命中精度或低帧率稳定性；生成器的结构核对也不等于重新生成并比较已提交 GLB 的二进制内容。哈希与字符串断言用于识别固定来源和关键入口，不能替代行为测试。

“屏幕位置 → 相机射线 → 命中点 → 头部局部坐标”的公式、求交边界和数值例子，见 [Flutter Scene 的坐标转换与射线拾取](Flutter-Scene坐标转换与射线拾取.md)。若需要判断性能，应使用 [运行时性能验证链](../engine/运行时性能验证链.md)明确测量端点；本节不从源码结构直接推导运行性能。

渲染器如何把这些节点与几何体组织成 GPU 绘制，以及骨骼上传、自动合批、纹理交接和测量口径，见 [Flutter Scene 的底层实现与性能边界](Flutter-Scene底层实现与性能边界.md)。该文单独固定库与 Engine 的源码基线，本案例仍沿用上表版本。

抚摸动作如何连接页面上的粒子、角色反馈与松手后的余韵，见 [Flutter 触摸粒子反馈与爱心动效](Flutter-触摸粒子反馈与爱心动效.md)。

[app-repo]: https://github.com/bdero/lantern_spirit/tree/bc151089f4ecfeae6675ef98731b55f8770ed39b
[scene-repo]: https://github.com/bdero/flutter_scene/tree/b8023c6261ed77ed4046d72c86496ed40c96b37b
[dependency]: https://github.com/bdero/lantern_spirit/blob/bc151089f4ecfeae6675ef98731b55f8770ed39b/pubspec.yaml#L14-L35
[app-main]: https://github.com/bdero/lantern_spirit/blob/bc151089f4ecfeae6675ef98731b55f8770ed39b/lib/main.dart#L10-L45
[boot]: https://github.com/bdero/lantern_spirit/blob/bc151089f4ecfeae6675ef98731b55f8770ed39b/lib/ui/loading_screen.dart#L39-L76
[preload]: https://github.com/bdero/lantern_spirit/blob/bc151089f4ecfeae6675ef98731b55f8770ed39b/lib/app/preload.dart#L62-L140
[rig]: https://github.com/bdero/lantern_spirit/blob/bc151089f4ecfeae6675ef98731b55f8770ed39b/tool/make_lantern_glb.py
[character]: https://github.com/bdero/lantern_spirit/blob/bc151089f4ecfeae6675ef98731b55f8770ed39b/lib/lantern/character.dart
[park]: https://github.com/bdero/lantern_spirit/blob/bc151089f4ecfeae6675ef98731b55f8770ed39b/lib/ui/park_screen.dart#L1432-L1467
[app-clock]: https://github.com/bdero/lantern_spirit/blob/bc151089f4ecfeae6675ef98731b55f8770ed39b/lib/app/scene_clock.dart#L10-L20
[node]: https://github.com/bdero/flutter_scene/blob/b8023c6261ed77ed4046d72c86496ed40c96b37b/packages/flutter_scene/lib/src/node.dart#L496-L523
[player]: https://github.com/bdero/flutter_scene/blob/b8023c6261ed77ed4046d72c86496ed40c96b37b/packages/flutter_scene/lib/src/animation/animation_player.dart#L114-L152
[resolver]: https://github.com/bdero/flutter_scene/blob/b8023c6261ed77ed4046d72c86496ed40c96b37b/packages/flutter_scene/lib/src/animation/property_resolver.dart#L118-L220
[scene-update]: https://github.com/bdero/flutter_scene/blob/b8023c6261ed77ed4046d72c86496ed40c96b37b/packages/flutter_scene/lib/src/scene.dart#L1962-L1972
[scene-view]: https://github.com/bdero/flutter_scene/blob/b8023c6261ed77ed4046d72c86496ed40c96b37b/packages/flutter_scene/lib/src/widgets/scene_view.dart
[soft]: https://github.com/bdero/lantern_spirit/blob/bc151089f4ecfeae6675ef98731b55f8770ed39b/lib/lantern/soft_body.dart#L244-L278
[face]: https://github.com/bdero/lantern_spirit/blob/bc151089f4ecfeae6675ef98731b55f8770ed39b/assets/face.fmat#L33-L48
