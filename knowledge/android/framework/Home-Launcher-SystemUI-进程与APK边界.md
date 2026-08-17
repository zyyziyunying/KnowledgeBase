# Home、Launcher 与 SystemUI：进程与 APK 边界

## 一句话结论

Android 启动链中的 **Home** 与 **SystemUI** 通常都是 APK，但不是同一个 APK：Home 是由系统解析并启动的桌面 Activity；SystemUI 是由 `system_server` 启动的特权系统应用和持久进程。AMS、ATMS、WMS 仍位于 `system_server`，SurfaceFlinger、Boot Animation 等则是 native 进程，不能把所有“屏幕上看得见的东西”都归为一个系统界面 APK。

> **适用边界**：本文以 AOSP main 的固定源码 revision 为事实源，核对日期为 2026-08-17。Launcher、SystemUI 的模块名、包名、进程拆分、功能范围和预装策略都可能被设备厂商修改；本文说明的是 AOSP 模型，不代表所有量产设备拥有相同 APK 清单。

关键结论、固定 revision、SHA-256 和可执行断言记录在 [Home 与 SystemUI 证据包](../../../evidence/android/framework/home-system-ui/manifest.json)。

## 先区分四个概念

| 概念 | 回答的问题 | AOSP 示例 |
| --- | --- | --- |
| APK / package | 代码、资源和组件以什么安装单元交付 | `com.android.launcher3`、`com.android.systemui` |
| Activity / Service | APK 对 Framework 暴露什么组件 | Launcher Activity、SystemUIService |
| process | 组件运行在哪个 Linux 进程 | Launcher 应用进程、`com.android.systemui`、`system_server` |
| System Service / native service | 谁掌握系统级状态和底层能力 | AMS、ATMS、WMS、SurfaceFlinger |

“它是不是 APK”和“它是不是独立进程”是两个问题。一个 APK 可以包含多个组件并使用多个进程；多个 Framework Service 也可以共同运行在一个 `system_server` 进程中。

## 总体关系

```text
system_server
├── SystemServer.startSystemUi()
│      └── SystemUI.apk / com.android.systemui
│          ├── SystemUIService
│          └── 状态栏、快捷设置、导航、Keyguard 等系统 UI 模块
│
└── AMS / ATMS / WMS 协作解析 HOME Intent
       └── Launcher3.apk / 厂商或用户选择的 Home APK
           └── Home Activity，也就是桌面入口

独立 native 进程
├── SurfaceFlinger：合成 Surface buffer
└── bootanimation：播放启动动画
```

这里的箭头表示启动或协作关系，不表示所有组件都由同一个进程绘制。

## Home：一个角色，不是写死的类名

### AOSP Launcher3 确实构建为 APK

Launcher3 的构建文件使用 `android_app` 模块并声明 `name: "Launcher3"`，同时把它标记为 privileged、放在 system_ext 侧。它的 Manifest 包名是 `com.android.launcher3`。对应固定源码：[Launcher3 Android.bp](https://android.googlesource.com/platform/packages/apps/Launcher3/+/2663cf0a414bd603d6a833cb691cea76eb1897b7/Android.bp)、[Launcher3 AndroidManifest.xml](https://android.googlesource.com/platform/packages/apps/Launcher3/+/2663cf0a414bd603d6a833cb691cea76eb1897b7/AndroidManifest.xml)。

Launcher Activity 通过 Intent Filter 声明自己能够承担 Home：

```xml
<action android:name="android.intent.action.MAIN" />
<category android:name="android.intent.category.HOME" />
<category android:name="android.intent.category.DEFAULT" />
```

因此 Home 更接近一个由系统解析的“桌面角色”，而不是 Framework 写死必须启动 `com.android.launcher3.Launcher`。AOSP 只是提供 Launcher3 作为实现；厂商可以预装自己的 Launcher，允许用户选择其他 Home，或者在受管设备上固定某个 Home。

### Framework 怎样启动 Home

当前 AOSP 的 `RootWindowContainer` 会按用户和显示区域取得 Home Intent，通过 PackageManager/ActivityTaskManager 解析出 `ActivityInfo`，把解析结果写入 Intent 的 Component，再启动 Home Activity。多显示设备还拥有 secondary Home 分支。固定源码入口：[RootWindowContainer.java](https://android.googlesource.com/platform/frameworks/base/+/1cdfff555f4a21f71ccc978290e2e212e2f8b168/services/core/java/com/android/server/wm/RootWindowContainer.java)。

这带来三个结论：

1. Home 是 Activity 调度模型的一部分，仍受用户、显示、PackageManager、ATMS/WMS 状态约束；
2. “按下 Home 键”和“开机启动桌面”最终可以汇入相同的 Home Activity 模型，但触发原因和当前状态不同；
3. Launcher 进程已经存在不等于桌面首帧已经合成，更不等于用户已经能够操作。

## SystemUI：独立 APK，也是特权持久进程

SystemUI 的 AOSP 构建模块同样是 `android_app`，模块名为 `SystemUI`，使用 platform certificate、platform APIs，并声明 privileged。它的 Manifest 包名是 `com.android.systemui`，Application 设置 `android:persistent="true"`，默认进程名为 `com.android.systemui`，并声明 `SystemUIService`。固定源码：[SystemUI Android.bp](https://android.googlesource.com/platform/frameworks/base/+/1cdfff555f4a21f71ccc978290e2e212e2f8b168/packages/SystemUI/Android.bp)、[SystemUI AndroidManifest.xml](https://android.googlesource.com/platform/frameworks/base/+/1cdfff555f4a21f71ccc978290e2e212e2f8b168/packages/SystemUI/AndroidManifest.xml)。

AOSP 自己把 SystemUI 描述为：在 `system_server` 之外、为系统提供 UI 的持久进程。其内部通过 `SystemUIApplication` 初始化依赖图和各个 SystemUI 模块，并大量使用平台私有 API 与 `system_server` 通信。[SystemUI README](https://android.googlesource.com/platform/frameworks/base/+/1cdfff555f4a21f71ccc978290e2e212e2f8b168/packages/SystemUI/README.md)。

典型职责包括状态栏、通知与快捷设置、系统导航、Keyguard、全局操作、截图、音量或生物识别等系统界面，但具体模块会随 Android 版本、设备形态和厂商定制变化。不能因为某个界面“看起来属于系统”，就断定它一定在 SystemUI 中。

## 谁启动 SystemUI

当前 `SystemServer.startSystemUi()` 从 `PackageManagerInternal` 获取配置的 SystemUI Service Component，再通过 `startServiceAsUser(..., UserHandle.SYSTEM)` 启动它，并通知 WindowManager SystemUI 已启动。固定源码：[SystemServer.java](https://android.googlesource.com/platform/frameworks/base/+/1cdfff555f4a21f71ccc978290e2e212e2f8b168/services/java/com/android/server/SystemServer.java)。

所以需要同时记住：

- SystemUI 由 `system_server` 协调启动，但运行在 `system_server` 之外；
- `system_server` 中的 System UI Context 只是系统进程使用的一种 Context，不等于 `com.android.systemui` APK；
- Home 解析和 SystemUI Service 启动是两条不同路径，替换 Home 不会自动替换或删除 SystemUI。

## 哪些“系统画面”不是 SystemUI APK

| 画面或能力 | 主要归属 | 为什么不能简单算作 SystemUI APK |
| --- | --- | --- |
| Activity/Task 调度、窗口层级与焦点 | ATMS / WMS，位于 `system_server` | SystemUI 也必须通过 Framework 管理自己的窗口 |
| 最终图层合成与送显 | SurfaceFlinger / HWC | 属于 native 图形链路，不在应用 APK 中完成 |
| Boot Animation | `bootanimation` native 进程 | 在完整 Home/SystemUI 可用前就能播放 |
| 设置页、权限页、Setup Wizard | 各自 APK | 它们是系统应用，但不等于 SystemUI |
| 桌面和应用列表 | Home/Launcher APK | 是被 Framework 选择的 Home Activity |

SystemUI 的 README 用“不是普通应用的系统画面”帮助建立直觉，但这不是严格的进程归属定义。判断具体界面时仍应追踪窗口 owner、包名、进程名和源码组件。

## 专用设备中的实际含义

对于 kiosk、电视、车机、相框等专用 Android 设备，可以把业务应用设计成 Home 候选或由设备策略固定为默认 Home。这样开机后的桌面入口就是该应用，而不是先启动传统 Launcher 再跳转业务页。

但以下事项彼此独立：

- 成为默认 Home，不等于获得 SystemUI 的平台权限；
- 替换 Launcher，不等于状态栏、导航栏或 Keyguard 自动消失；
- 隐藏系统栏，不等于卸载或停止 SystemUI；
- Home Activity resumed，不等于首帧已经由 SurfaceFlinger 合成；
- `sys.boot_completed=1`，不等于 Home 已经可交互。

设备是否允许第三方 Home、如何固定默认应用、能否裁剪 SystemUI，以及退出或恢复策略，属于产品配置、设备管理和厂商系统集成问题，应在具体项目的事实源中维护。

## 设备上的只读验证

先解析当前用户的 Home，再观察实际包和进程；AOSP 包名只是示例，厂商设备可能不同：

```bash
adb shell cmd package resolve-activity --brief \
  -a android.intent.action.MAIN \
  -c android.intent.category.HOME

adb shell pm path com.android.launcher3
adb shell pm path com.android.systemui
adb shell pidof com.android.systemui
adb shell dumpsys activity activities | grep -E 'mResumedActivity|topResumedActivity'
adb shell dumpsys window windows | grep -E 'mCurrentFocus|mFocusedApp'
```

- `resolve-activity` 回答“当前解析到哪个 Home Activity”；
- `pm path` 回答“这个 package 是否安装、APK 位于哪里”；
- `pidof` 回答“目标进程此刻是否存在”；
- Activity/Window dumpsys 回答“哪个 Activity resumed、哪个窗口获得焦点”。

这些命令仍不能单独证明首帧已经完成合成或输入响应正常；要验证可见与可交互里程碑，应结合 Perfetto、SurfaceFlinger/窗口状态和实际输入观测。

## 继续阅读

- [Android Framework 高频核心讲义](Android-Framework-%E9%AB%98%E9%A2%91%E6%A0%B8%E5%BF%83%E8%AE%B2%E4%B9%89.md)：启动主线、AMS/ATMS/WMS、渲染和输入基础。
- [Home 与 SystemUI 证据包](../../../evidence/android/framework/home-system-ui/manifest.json)：固定源码、哈希与断言。
