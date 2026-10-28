# Flutter 触摸粒子反馈与爱心动效

触摸粒子反馈可以把输入、模拟和绘制分开：用手指移动距离控制发射节奏，用每帧时间推进粒子，再分别设计出现、漂浮和消失。角色的姿态、表情与声音共享同一次交互，能让反馈形成连续的因果关系；视觉上的柔和与运行时帧率需要分别验证。

本文以 Lantern Spirit 的抚摸头顶效果解释可复用机制。爱心是覆盖在页面上的 Flutter 2D 绘制，角色仍由 3D 场景控制。范围限于常规头部抚摸路径，不维护案例应用的功能现状、设备表现或项目任务。角色节点与软体形变的基础见 [Flutter Scene 的动画与交互叠加](Flutter-Scene动画与交互叠加.md)。

## 源码基线与阅读入口

固定来源为作者的 [bdero/lantern_spirit][app-repo]，revision 为 `bc151089f4ecfeae6675ef98731b55f8770ed39b`，核对日期为 2026-10-28。主要实现是 [park_pet.dart][pet]；输入和页面刷新位于 [park_screen.dart][park]，逐帧调用经过 [park_life.dart][life] 和 [scene_clock.dart][clock]，角色响应位于 [character.dart][character]。

来源哈希、关键断言和下文 claim 映射见 [证据包](../../../evidence/flutter/scene/touch-particle-feedback/manifest.json)。这里记录的是固定开源实现，不是 Flutter SDK 对所有粒子系统的保证。

## 从头顶命中到距离发射

页面把拖动和长按移动接入同一组处理函数。拖动开始时先调用 `startPet`；如果起点落在头顶区域，后续移动进入 `movePet`，结束或取消时进入 `endPet`。普通点击另走戳碰逻辑，不能把所有触摸都视为抚摸。[输入分流][input]。对应证据：`touch-particle-001`。

头顶区域来自相机投影：把头中心和上方一点投影到头部视图，以两点距离估算屏幕半径，再检查触点是否落在头顶附近的矩形区域。这是屏幕空间的交互容差；实际按压位置另外通过相机射线与头部球体近似求交，并限制到头部上半部。[命中与按压位置][pet]

每次移动用当前与上次触点之间的距离 `stroke` 扣减发射阈值。以下为教学简写，不是可独立运行的完整组件：

```dart
remainingDistance -= (position - previousPosition).distance;
if (remainingDistance <= 0) {
  remainingDistance = randomBetween(90, 150);
  spawnHeart(position);
}
```

原实现触发后把阈值重设为约 90～150 个逻辑像素，并在触点上方 10 个逻辑像素、横向约 ±10 个逻辑像素处生成爱心。初始阈值是 0，因此首次 `movePet` 检查即可触发；按下本身不生成爱心。阈值也不会在每次 `startPet` 时清零。[发射入口][emit]

这种规则让主动发射大体跟随抚摸距离，但它不是严格等间距的轨迹采样：一次回调只检查一次阈值，超出量会被丢弃，也不会沿长线段补发多个发射点。输入事件的合并与采样方式仍会影响结果。高情绪时还有共用同一阈值的时间发射通道，见后文。

## 粒子的参数分布

每颗爱心保存屏幕位置、速度、尺寸参数、初始倾角、上下渐变颜色、寿命和年龄。随机数生成器使用固定种子 23；相同结果还需要相同的输入与随机调用序列。[粒子状态与初始化][pet]。对应证据：`touch-particle-002`。

| 参数 | 固定实现 | 视觉作用 |
| --- | --- | --- |
| 主要爱心尺寸参数 | `9 + 22 × random^1.8` | 分布偏向小值，偶尔出现较大的爱心 |
| 初始横向速度 | 约 -18～18 逻辑像素/秒 | 轻微分散 |
| 初始纵向速度 | `-40 - random × 30 - size` | 屏幕 Y 向下为正，负速度使爱心上浮；尺寸参数也参与初速度 |
| 初始倾角 | 约 -0.4～0.4 弧度 | 打散整齐排列 |
| 寿命 | `1.4 + size / 28` 秒 | 主要爱心约 1.72～2.51 秒 |
| 颜色 | 五组上下渐变色 | 在统一色调中保留差异 |
| 附带小爱心 | 每次发射约 30% 概率多一颗，尺寸参数约 6～10 | 形成大小搭配，寿命由相同公式计算 |

这里的 `size` 是轮廓构造参数，不应当作最终屏幕包围盒的精确高度。表中的区间作近似描述，原随机值取自 `[0, 1)`。

## 用时间推进漂浮

`tickPet` 对每颗爱心增加年龄，更新速度，再用新速度推进位置。省略变量前缀后的等价关系如下，`dt` 单位为秒：[运动更新][motion]。对应证据：`touch-particle-003`。

```text
age += dt
vx = vx × exp(-1.5 × dt) + sin(age × 4 + spin × 9) × 140 × dt
vy = vy × exp(-0.6 × dt)
position += velocity × dt
```

纵向速度逐渐接近 0，让爱心越升越慢；横向速度同时受到阻尼和正弦驱动，产生飘摆。每颗爱心的 `spin` 不同，横向驱动的相位也不同。年龄达到寿命后，粒子从数组移除。

用 `dt` 表达速度和衰减，使动画具有明确的时间单位。指数阻尼本身有良好的时间步组合性质，但正弦驱动的离散采样和位置积分仍受步长影响，不能据此宣称任意帧率下轨迹完全一致。`tickPet` 本身没有限制 `dt`；角色控制器内部的时间步限制也不会反向作用于已经更新的爱心。

## 分阶段控制出现与消失

画笔用 `u = age / life` 得到生命周期进度，然后分别计算尺寸、透明度和角度。[画笔实现][paint]。对应证据：`touch-particle-004`。

| 维度 | 规则 |
| --- | --- |
| 弹出 | `u < 0.12` 时使用 `elasticOut(u / 0.12)`，之后弹出系数为 1 |
| 缓慢变大 | 尺寸再乘 `1 + 0.15 × u` |
| 淡出 | 前 60% 保持不透明，后 40% 用 `1 - (u - 0.6) / 0.4` 衰减 |
| 摇摆角度 | `spin + sin(age × 3 + spin × 5) × 0.18` |

例如取尺寸参数 20，寿命约 2.11 秒，则弹出阶段约 0.25 秒，约 1.27 秒后开始淡出。这是公式算例，不是实测时序。分开的曲线让爱心先明确出现，再漂浮，最后逐渐消失；不需要让所有属性同时线性变化。

爱心轮廓由两段三次贝塞尔曲线闭合而成。每颗爱心按以下顺序绘制：

1. 带模糊的彩色轮廓，形成外侧光晕。
2. 上浅下深的渐变心形主体。
3. 左上方的小椭圆高光。

饱满感来自这些 2D 绘制层次。粒子生成后保存自己的屏幕位置与速度，之后自行漂浮，不会每帧重新贴到手指或角色头部上。

## 角色响应和松手后的余韵

`movePet` 同时积累 `level` 情绪值、记录手指相对头顶的左右位置，并调用角色的 `pet` 按压方法。后者设置软体按压和整体压缩目标；松手时释放按压。倾斜则由 `petLean` 提供目标，角色内部以 `1 - exp(-4 × dt)` 平滑接近。[抚摸逻辑][pet]、[角色响应][character]。对应证据：`touch-particle-005`。

随着情绪积累，角色会倾斜、改变表情并增强发光；更高情绪下出现缓慢摇摆。单次位移通过 `gentle` 系数影响情绪增量，但代码没有用该位移除以时间，因此不能把这个系数直接解释为严格的手速测量。

松手后，情绪大于 0.75 时按每秒 0.05 衰减，其他情况下按每秒 0.16 衰减。已有爱心继续走完自己的生命周期。满足“情绪大于 0.55 且已松手”，或进入高情绪摇摆状态时，代码还会按 `dt` 扣减发射阈值；触发后把阈值设为约 70～120，并在投影后的头部位置附近生成爱心。

主动抚摸扣距离、情绪余韵扣时间，两个通道共用 `toNextHeart`。因此“90～150 个逻辑像素”只描述主动移动通道重设阈值的规则，不是所有状态下的固定发射间隔。高情绪摇摆时，即使仍在抚摸，时间通道也可能参与。

换向时的轻柔音效和发射爱心的音效也有最小播放间隔。它们与动作共同构成反馈，但音效节流不等于粒子节流。[声音调用][pet]

## 逐帧调用与重绘边界

常规头部路径的关系是：[页面回调][tick]、[生活状态更新][life]、[场景时钟封装][clock]。对应证据：`touch-particle-006`。

```text
SceneView 的帧回调
  → 页面 onTick
    → lifeTick
      → tickPet：更新情绪与爱心
    → character.update：更新角色
  → scene.update
```

爱心层是 `Positioned.fill → IgnorePointer → CustomPaint`，所有爱心由同一个画笔遍历绘制。`IgnorePointer` 让这一层不拦截底下的触摸；它不是渲染优化开关。

此版本在更新后仍有爱心或情绪值大于 0 时调用 `_refresh()`，其实现是页面 `setState`。重建爱心层时，会复制列表并创建画笔，`shouldRepaint` 始终返回 `true`。所以不能把这段效果描述为“只通知画笔重绘，页面完全不重建”。同样，一次 `setState` 也不能直接推导出所有子节点都重新布局。[爱心层][paint]、[刷新入口][refresh]

模糊光晕、绘制面积、粒子数量、页面重建和同时运行的 3D 场景都可能贡献成本。要判断瓶颈，应在目标构建和设备上分别观察 UI、raster 与 GPU，测量方法见 [运行时性能验证链](../engine/运行时性能验证链.md)。上述源码机制未验证具体设备帧率、输入延迟或低帧率稳定性。

并行运行的 3D 场景如何更新、上传几何体并交给 Flutter 合成，见 [Flutter Scene 的底层实现与性能边界](Flutter-Scene底层实现与性能边界.md)。应把这部分与爱心画笔、页面刷新分别测量；库的实现细节以各文固定版本为准。

## 复现与验证顺序

先独立实现“位移发射 → 粒子数组 → 时间更新 → 统一画笔”的 2D 效果，再连接角色姿态、表情与声音。学习时可按以下顺序比较：

1. 固定尺寸、颜色和初速度，只观察触摸距离与发射节奏。
2. 加入阻尼、横向飘摆、弹出和淡出，分别检查各阶段是否连续。
3. 加入有界的参数差异和附带小爱心，再连接角色与情绪余韵。

移植时如需严格按距离均匀发射，应保留剩余距离、沿输入线段插值发射点，并考虑每次补发数量的上限；如需缩小重建范围，可评估独立粒子状态和画笔重绘通知。这些是由当前机制导出的改进方向，不是案例已采用或已测量有效的优化。

有意义的验证包括：相同轨迹采用不同输入采样密度；相同总时间采用不同帧步长；松手后已有粒子完成淡出；失效粒子被移除且画面及时清空；爱心覆盖层不拦截交互。哈希和字符串断言仅核对来源与入口，不替代这些行为验证。

[app-repo]: https://github.com/bdero/lantern_spirit/tree/bc151089f4ecfeae6675ef98731b55f8770ed39b
[pet]: https://github.com/bdero/lantern_spirit/blob/bc151089f4ecfeae6675ef98731b55f8770ed39b/lib/ui/park_pet.dart
[park]: https://github.com/bdero/lantern_spirit/blob/bc151089f4ecfeae6675ef98731b55f8770ed39b/lib/ui/park_screen.dart
[life]: https://github.com/bdero/lantern_spirit/blob/bc151089f4ecfeae6675ef98731b55f8770ed39b/lib/ui/park_life.dart#L166-L180
[clock]: https://github.com/bdero/lantern_spirit/blob/bc151089f4ecfeae6675ef98731b55f8770ed39b/lib/app/scene_clock.dart
[character]: https://github.com/bdero/lantern_spirit/blob/bc151089f4ecfeae6675ef98731b55f8770ed39b/lib/lantern/character.dart
[input]: https://github.com/bdero/lantern_spirit/blob/bc151089f4ecfeae6675ef98731b55f8770ed39b/lib/ui/park_screen.dart#L998-L1040
[emit]: https://github.com/bdero/lantern_spirit/blob/bc151089f4ecfeae6675ef98731b55f8770ed39b/lib/ui/park_pet.dart#L79-L101
[motion]: https://github.com/bdero/lantern_spirit/blob/bc151089f4ecfeae6675ef98731b55f8770ed39b/lib/ui/park_pet.dart#L208-L215
[paint]: https://github.com/bdero/lantern_spirit/blob/bc151089f4ecfeae6675ef98731b55f8770ed39b/lib/ui/park_pet.dart#L218-L269
[tick]: https://github.com/bdero/lantern_spirit/blob/bc151089f4ecfeae6675ef98731b55f8770ed39b/lib/ui/park_screen.dart#L1432-L1467
[refresh]: https://github.com/bdero/lantern_spirit/blob/bc151089f4ecfeae6675ef98731b55f8770ed39b/lib/ui/park_screen.dart#L1932-L1934
