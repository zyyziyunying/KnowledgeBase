# 系统更新UI与Home无缝切换

## 一句话结论

OTA 更新 Home 时换包发生在开机早期（PMS systemReady 末尾、第三方应用启动之前），全程由 bootanimation 覆盖；bootanim **不会自己退场**，而是由系统在 boot 完成、屏幕启用时显式让它退出——这就是 Windows"重启后显示更新界面直到新桌面就绪"在 Android 的系统层等价物。运行态 `pm install -r` + 重启 Home 之所以黑屏，是因为换包发生在"活的"前台 Home 上且没有任何覆盖层。

> **适用边界**：本文以 AOSP 固定源码 revision 为事实源，核对日期为 2026-08-18。frameworks/base 统一钉在 `1cdfff555f4a21f71ccc978290e2e212e2f8b168`（与启动、Home/SystemUI、系统应用更新证据包同一基线）；recovery 钉在 `9565b5ee790a4ae7acd0c6c04a2b3e0c7eeced3c`。关键结论、SHA-256 与可执行断言记录在 [系统更新UI与Home无缝切换证据包](../../../evidence/android/framework/update-ui/manifest.json)。GMS 的更新屏（`com.google.android.gms`）是闭源实现，只作行业惯例观察，不构成 AOSP 事实源。换包本身的安装机制（data override、staged、冻结/杀进程）见 [系统应用更新与 OTA](%E7%B3%BB%E7%BB%9F%E5%BA%94%E7%94%A8%E6%9B%B4%E6%96%B0%E4%B8%8EOTA.md)，本文不重复其结论。

## 先纠正前提：黑屏不是 OTA 的必然产物

两条换包路径的视觉结果完全不同：

- **OTA/staged 路径**：换包发生在 systemReady 末尾（第三方应用启动之前，见系统应用更新证据包 claim upd-004），随后 bootanim 一直覆盖到 boot 完成、屏幕启用。用户看到的是"开机动画 → 新 Home"，物理上不存在黑屏窗口。
- **in-place 路径（运行态换包）**：旧 Home 进程被冻结/杀掉（见系统应用更新证据包 claim upd-006/upd-007），home task 区域没有任何窗口接管，直到新 launcher 首帧绘制前就是"黑一下"。注意 SystemUI 是独立进程仍在绘制，所以通常只黑 home task 区域而非全屏；若 SystemUI 也被替换，才会全屏黑。

## 开机动画何时退场（核心机制）

bootanim 的退场是系统显式触发的，链条在固定 revision 中完整可见：

```text
bootanim.rc：service bootanim /system/bin/bootanimation（core/animation class、disabled、oneshot）
        ↓
BootAnimation::checkExit()：轮询属性 service.bootanim.exit
        ↓ 属性置 1 后 requestExit()
WMS.enableScreenAfterBoot()                 (WindowManagerService.java:3847)
  → performEnableScreen
      → SystemProperties.set("service.bootanim.exit", "1")   (:3952)
      → SurfaceControl.bootFinished()                        (:3961)
      → mActivityManager.bootAnimationComplete()             (:3976)
        ↓
AMS.bootAnimationComplete()                 (ActivityManagerService.java:5321)
  → mBootAnimationComplete = true → finishBooting()
AMS.ensureBootCompleted()                   (:5414)
  → finishBooting()（仍在 booting 时）
  → mAtmInternal.enableScreenAfterBoot(mBooted)              (:5429)
```

含义：bootanim 一直盖到 **boot 完成、屏幕正式启用**为止，之后接手的是 SystemUI/Keyguard、再是 Home。因此"换包发生在 bootanim 之下"不是巧合，而是这条退场链的必然结果。

## Framework 的防闪机制：ThemeHomeDelay

系统内存在"等就绪信号再显示 Home"的成熟模式：AMS 的 ThemeHomeDelay 允许**推迟 Home 启动**，直到 `ThemeOverlayController` 报告主题就绪（`setThemeOverlayReady`），超时 `HOME_LAUNCH_TIMEOUT_MS = 15000` 兜底强启。运行态更新幕布（见下）本质上是把同一模式搬到更新场景。

## Windows 式更新屏的 Android 对应物

| Windows 现象 | Android 对应物 | 实现层 |
| --- | --- | --- |
| "Working on updates" 关机更新 | update_engine A/B 后台安装 + 重启切换槽位 | 系统层，无需 UI |
| 重启后的"正在更新"进度屏 | recovery minui：`ScreenRecoveryUI::SetSystemUpdateText` 选择 `installing_text` / `installing_security_text` 位图 | recovery（minui 直接画 framebuffer） |
| 开机动画 | bootanimation + 上面的显式退场链 | 系统层 |

补充观察：Google 设备的模块更新屏（`com.google.android.gms.update.SystemUpdateActivity`）是闭源实现，其公开原理是：由特权应用在开机早期拉起全屏 Activity（`showWhenLocked`、`FLAG_KEEP_SCREEN_ON`），从 update_engine 状态读进度画进度条。厂商自研更新屏可以照此原理实现，但这是实现模式讨论，不是 AOSP 事实。

## 自研硬件的方案矩阵

按推荐度排序：

1. **staged/OTA + 重启（推荐）**：换包发生在 systemReady（第三方应用启动前）→ bootanim 覆盖 → "开机动画 → 新 Home"，无黑屏窗口。要更"Windows"，可在 boot 早期拉起自研更新屏直到新 Home 首帧。
2. **更新幕布（不重启的硬需求）**：顺序严格为——先盖全屏"正在更新"层（priv-app 或 WindowManager 加 Surface）→ `pm install -r` → 杀旧 Home → 显式拉起新 Home → 等首帧就绪信号 → 撤幕布。任何一步顺序颠倒都会露出黑屏。
3. **冻结帧快照手交（最顺滑）**：`SurfaceControl` 截下旧 Home 当前画面作幕布（或新 Home 的 SplashScreen 背景）→ 换包 → 新 Home 首帧后淡出快照。用户看到"画面定格 → 新桌面"。
4. **SplashScreen（最低成本）**：Android 12+ 让冷启动间隙显示品牌 splash，把黑屏换成有内容的过渡。
5. **熄屏/调暗兜底**：换包前亮度置 0 或熄屏，完成后恢复。体验一般，仅作兜底。

**反模式**：无覆盖的 `install -r` + 重启 Home，即"黑闪一下"的来源。

## 兜底与回滚

data override 机制天然保留旧系统副本，给了回退后路：

- `adb shell pm uninstall <pkg>`：卸载 data override，删除路径调用 `enableSystemPackageLPw` 恢复系统副本生效（证据包 claim upd-ui-005）；
- Android 10+ 的 `pm rollback-app`（RollbackManager）整包回退；
- 对比：`pm install-existing` 的语义是"为（新）用户重新安装已装应用"，不恢复系统副本，勿混淆；
- 注意：新 Home crash-loop 时系统是否自动切换其他 Home 候选未验证（`ROLE_HOME` 默认值不变的模型不能直接推出切换行为，见待验证清单），因此自研硬件上"更新屏 + 可回退兜底"是刚需而非可选。

## 源码入口（固定 revision）

frameworks/base 均为 `1cdfff555f4a21f71ccc978290e2e212e2f8b168`，SHA-256 与断言见证据包：

- [WindowManagerService.java](https://android.googlesource.com/platform/frameworks/base/+/1cdfff555f4a21f71ccc978290e2e212e2f8b168/services/core/java/com/android/server/wm/WindowManagerService.java)：`enableScreenAfterBoot` / `performEnableScreen` 退场链；
- [ActivityManagerService.java](https://android.googlesource.com/platform/frameworks/base/+/1cdfff555f4a21f71ccc978290e2e212e2f8b168/services/core/java/com/android/server/am/ActivityManagerService.java)：`bootAnimationComplete` / `ensureBootCompleted` / `finishBooting` / ThemeHomeDelay；
- [SurfaceControl.java](https://android.googlesource.com/platform/frameworks/base/+/1cdfff555f4a21f71ccc978290e2e212e2f8b168/core/java/android/view/SurfaceControl.java)：`bootFinished()`；
- [BootAnimation.cpp](https://android.googlesource.com/platform/frameworks/base/+/1cdfff555f4a21f71ccc978290e2e212e2f8b168/cmds/bootanimation/BootAnimation.cpp)：`checkExit()` 轮询 `service.bootanim.exit`；
- [bootanim.rc](https://android.googlesource.com/platform/frameworks/base/+/1cdfff555f4a21f71ccc978290e2e212e2f8b168/cmds/bootanimation/bootanim.rc)：bootanim 服务定义（core/animation class、disabled、oneshot）；
- [PackageManagerShellCommand.java](https://android.googlesource.com/platform/frameworks/base/+/1cdfff555f4a21f71ccc978290e2e212e2f8b168/services/core/java/com/android/server/pm/PackageManagerShellCommand.java)：`uninstall` 命令与 `install-existing` 的真实语义；
- [InstallPackageHelper.java](https://android.googlesource.com/platform/frameworks/base/+/1cdfff555f4a21f71ccc978290e2e212e2f8b168/services/core/java/com/android/server/pm/InstallPackageHelper.java)：删除路径 `restoreDisabledSystemPackageLIF` 恢复系统副本；
- [Settings.java](https://android.googlesource.com/platform/frameworks/base/+/1cdfff555f4a21f71ccc978290e2e212e2f8b168/services/core/java/com/android/server/pm/Settings.java)：`enableSystemPackageLPw` 回退路径（disable 侧见系统应用更新证据包）；
- [screen_ui.cpp](https://android.googlesource.com/platform/bootable/recovery/+/9565b5ee790a4ae7acd0c6c04a2b3e0c7eeced3c/recovery_ui/screen_ui.cpp)：recovery 更新屏位图选择（revision `9565b5ee790a4ae7acd0c6c04a2b3e0c7eeced3c`）。

## 设备上的只读验证

```bash
# bootanim 状态与退场属性
adb shell getprop init.svc.bootanim
adb shell getprop service.bootanim.exit

# 卸载 data override 恢复系统副本（更新 Home 后出问题的兜底）
adb shell pm uninstall <pkg>

# Home 解析是否仍正常
adb shell cmd package resolve-activity --brief \
  -a android.intent.action.MAIN \
  -c android.intent.category.HOME
```

这些命令回答"bootanim 是否还在跑、退场属性是否置位、能否回退、Home 解析是否正常"；"首帧已合成、用户可交互"仍需 Perfetto 与 SurfaceFlinger/输入观测，同 [Home/SystemUI 文档](Home-Launcher-SystemUI-%E8%BF%9B%E7%A8%8B%E4%B8%8EAPK%E8%BE%B9%E7%95%8C.md) 的边界。

## 待验证清单

已由证据包断言的机制不在此列；以下仍待后续核对：

- [ ] GMS `SystemUpdateActivity` 的具体实现与启动时机（闭源，仅行业观察）；
- [ ] ThemeHomeDelay 的触发条件（哪些场景 Home 启动可延迟）与 `ThemeOverlayController` 的完整交互；
- [ ] `SurfaceControl.bootFinished()` 在 SurfaceFlinger 侧的完整行为；
- [ ] 快照手交（SurfaceControl 截图 + splash 注入）的设备级实现细节（z-order、输入屏蔽、多用户）；
- [ ] 自研更新屏在目标设备上的最佳拉起时机（对应哪个 boot phase）；
- [ ] init 侧 `stop bootanim` 触发位置：已核对 core `a3b721a32242` 的 `rootdir/init.rc` 无该 trigger（仅有 `mkdir /data/misc/bootanim`），若存在于其他 rc 文件，其位置待定位；bootanim 退出本身以 `checkExit()` 轮询属性为准；
- [ ] 新 Home crash-loop 时系统是否自动切换 Home 候选（正文仅按 `ROLE_HOME` 解析模型说明，未验证实际切换行为）。

## 继续阅读

- [系统更新UI与Home无缝切换证据包](../../../evidence/android/framework/update-ui/manifest.json)：本文关键结论的固定源码、SHA-256 与可执行断言；
- [系统应用更新与 OTA](%E7%B3%BB%E7%BB%9F%E5%BA%94%E7%94%A8%E6%9B%B4%E6%96%B0%E4%B8%8EOTA.md)：换包安装机制（data override、staged、冻结/杀进程）；
- [Home、Launcher 与 SystemUI：进程与 APK 边界](Home-Launcher-SystemUI-%E8%BF%9B%E7%A8%8B%E4%B8%8EAPK%E8%BE%B9%E7%95%8C.md)：Home 角色模型与 APK 边界的事实源；
- [Android 建设路线](../ROADMAP.md)：第二阶段（图形与显示链路）与本主题的规划关系。
