# 系统应用更新与 OTA：从 data override 到 staged 提交

## 一句话结论

更新一个系统应用（含 Home）有三条需分开的路径：运行态 data override 在 `/data/app` 安装新副本；PackageInstaller staged session 在重启后由 PMS 的 `systemReady` 收尾逻辑恢复，其中 APEX 由 `apexd` 在更早的开机阶段激活，`StagingManager` 确认激活结果后再安装会话中的 APK；legacy A/B 或 Virtual A/B OTA 则由 `update_engine` 预先写非当前槽位或 COW 快照，重启后从新系统图像正常启动，PMS 在开机扫描时看到新的系统 APK。Home 作为 `ROLE_HOME` + intent 解析的默认应用，可在包/组件和角色持有者不变时继续命中新版本；但更新还必须满足签名 lineage、原系统副本的权限基线与当前系统图像配置。

> **适用边界**：本文以 AOSP 固定源码 revision 为事实源，最新核对日期为 2026-08-20。frameworks/base 统一钉在 `1cdfff555f4a21f71ccc978290e2e212e2f8b168`（与启动、Home/SystemUI 证据包同一基线）；`android.app.role` 已移入 Permission 模块，钉在 `26231a7eac744c7d2a8fea4740926620f56b20c6`。A/B OTA 路径使用有更新日期的 AOSP 官方文档，不冒充固定快照。关键结论、SHA-256 与可执行断言记录在 [系统应用更新与 OTA 证据包](../../../evidence/android/framework/system-app-update/manifest.json)。Home/Launcher 的角色模型以 [Home、Launcher 与 SystemUI：进程与 APK 边界](Home-Launcher-SystemUI-%E8%BF%9B%E7%A8%8B%E4%B8%8EAPK%E8%BE%B9%E7%95%8C.md) 为事实源，本文不重复其结论。

> **版本边界**：本文钉住的 revision 中，默认 Home 由 RoleManager 的 `ROLE_HOME` 角色（经 `DefaultAppProvider`）维护，preferred activity 仅作为角色切换窗口期的回退；本文不声称任何旧版 PackageManager 持久化 API 是或曾是事实源。launcher 更新后无缝接管的结论以"解析入口 + 角色默认值不变"成立，不依赖特定版本的持久化实现。

## 先分清三个问题

"更新 Home APK"叠加了三类不同问题，分开讨论才不会混：

1. **安装通道**：新 APK 从哪来（OTA 包、PackageInstaller、自建商店）、怎样落盘（直接安装还是 staging）；
2. **生效者**：装完哪个副本生效、Home 角色如何解析、旧进程如何切换；
3. **硬件约束**：签名策略、priv-app 白名单、分区布局决定了哪些通道可用。

## 决策起点：包类别决定自由度

系统应用的更新自由度由**签名**和 **privileged 状态**锁死：

| 类别 | 例子 | 能否走商店/独立安装更新 |
| --- | --- | --- |
| platform 签名 + priv-app | AOSP Launcher3（system_ext） | OEM 可走 OTA；若使用 data override/staged，必须严格控制 platform key 与系统权限迁移 |
| vendor 自有签名 + priv-app 或普通预装 | OEM 自研桌面 | 可走 OTA 或受控的 data override/staged，但快速通道不能超出原系统权限基线 |
| 普通签名预装 / 三方桌面 | 用户安装的 Launcher | 走 Play/商店，最自由 |

两条硬约束：

- **签名延续**：同包名覆盖安装要求当前签名相容，否则报 `INSTALL_FAILED_UPDATE_INCOMPATIBLE`。Android 9 引入 APK Signature Scheme v3 的 proof-of-rotation，Android 13 引入 v3.1 的 SDK 定向轮换；当前 AOSP 校验 updated system app 时也会核对预装副本的 signing lineage 与 `INSTALLED_DATA` / `ROLLBACK` capability。因此系统应用不是一概禁止 key rotation，但 platform 签名、shared UID、signature permission 与低版本设备会扩大迁移面，必须用签名 lineage 与 CTS/目标设备验证后才能采用。
- **原系统副本的权限基线**：对系统图像中的 priv-app，`privapp-permissions-*.xml` 在开机扫描时被校验，强制模式下的违规会在 permission policy `onSystemReady` 阶段阻断继续。但 `/data/app` 中的 updated system app 不依靠重复的 privapp allowlist 条目过关；它能否获得 privileged/OEM permission，取决于被禁用的原系统副本是否已请求并有资格获得该权限。所以只预留 XML 白名单不足以让 data override 引入全新特权权限；需要先通过 OTA 更新系统 APK 的 manifest 与相应权限配置。

## 更新路线与取舍

### 路线 A：随系统 OTA（最正统，兜底必选）

Home 位于 system_ext/system/product 等只读分区时，legacy A/B 由 `update_engine` 在当前系统运行期写入非活动槽位；Virtual A/B 对物理分区写新槽位、对动态分区把增量写入 Android COW 快照，并在重启验证后合并快照。PMS 随后在新系统的正常开机扫描中读取新 Home APK；这不是 PackageInstaller staged session 的 `restoreAndApplyStagedSessionIfNeeded`。适合 platform 签名、低频变更、需同步修改系统 APK 权限基线与配置的场景。缺点是发版节奏被系统 OTA 锁定，无法单独快速修 Home 的 bug。

### 路线 B：data override（OEM 自研桌面主流做法）

更新系统 APK 时**不替换系统分区副本**，而是在 `/data/app/` 安装新副本；PMS 把系统副本移入 disabled 集合（代码与资源路径保留，见 `Settings.disableSystemPackageLPw`），并把新副本标记为 updated system app，data 副本成为生效包（codePath 指向 `/data/app/` 下新生成的两段随机路径）。重启后依然生效——系统副本已持久化在 disabled 集合中，data 副本是生效包。前提是签名或 signing lineage 相容，且所需 privileged/OEM 权限已存在于原系统副本的 manifest 与授权基线；单独预留 allowlist 不足以让 data override 引入新特权权限。可用 `adb install -r`、PackageInstaller Session 或自建商店实现。

### 路线 C：staged install（原子批量更新正道）

`PackageInstaller` Session 配合 `setStaged()` 把会话标记为"重启时安装"；PMS 在**开机 systemReady 末尾**通过 `restoreAndApplyStagedSessionIfNeeded` 恢复 staged 会话。APK-only 会话由 `StagingManager` 继续安装 APK；含 APEX 的会话则由 `apexd` 在此之前的开机阶段激活 APEX，`StagingManager` 只验证 APEX 已进入 activated/success 状态，再安装同一会话中的 APK 并完成收尾，`PHASE_BOOT_COMPLETED` 时标记成功。多包 staged session 可以组合 APK/APEX 并提供原子提交语义，但 PMS 不负责激活 APEX。这是 PackageInstaller 的重启安装路径，不等同于系统 OTA 的槽位/快照更新。

### 路线 D：普通签名应用 + 自家商店

Home 不需要特权权限时最省事：预装为普通应用，走标准覆盖安装更新。Framework 天然支持"换包"，因为 Home 由 intent 解析得出。

### 推荐组合（自研硬件场景）

priv-app 的预装 APK manifest 与系统权限配置维护一致基线 + **OTA 作为引入新特权权限和系统配置的通道** + data override 或 staged 作为不超出原系统权限基线的快速通道 + RollbackManager（`pm rollback-app`，Android 10+）兜底回滚。通道可以并存，但签名 lineage、shared UID 和权限基线必须按目标 Android 版本协同设计。

## Framework 内部链路

三条更新路径不共享同一个"安装时点"，但最终都回到同一条 Home 解析链：

```text
data override：PackageInstaller Session → PMS commit/scan
      → 写入 Settings（packages.xml：新 PackageSetting 与 codePath）
      → 系统副本移入 disabled 集合（Settings.disableSystemPackageLPw）
      → 广播 ACTION_PACKAGE_REPLACED
      → 安装期间被替换包由 PackageFreezer 冻结（REASON_PACKAGE_UPDATED）；
      是否杀旧进程由 INSTALL_DONT_KILL_APP 安装标志决定（桌面进程当场退出）

staged session：重启 → apexd 在早期开机阶段激活会话中的 APEX（如有）
      → PMS systemReady 末尾 restoreAndApplyStagedSessionIfNeeded
      → StagingManager 验证 APEX 激活结果、安装 APK 部分并完成会话收尾

A/B OTA：update_engine 写非当前槽位/快照 → 重启切换新系统
      → PMS 开机扫描新系统分区中的 Home APK

三条路径都回到当前包状态快照
      → ComputerEngine.getHomeActivitiesAsUser 解析 ACTION_MAIN + CATEGORY_HOME
      → getDefaultHomeActivity 通过 ROLE_HOME 的 DefaultAppProvider 取默认桌面
      → preferred activity 仅作为角色切换窗口期的回退
      → 需要桌面时由 Window 侧（RootWindowContainer，解析链路见
      Home/SystemUI 证据包）拉起当前生效的 Home Activity
```

关键结论：

- 对 data override，包名/组件名与 `ROLE_HOME` 持有者不变 → 默认 Home 继续命中当前生效副本，通常无需重启整机或修改 Framework 的 Home 解析配置；
- 默认组件已不存在（如换包名）→ 回退到重新解析候选列表；
- staged 场景中 APEX 由 `apexd` 在早期开机阶段激活，PMS `systemReady` 末尾负责恢复会话并由 `StagingManager` 安装 APK 部分、完成收尾；A/B OTA 则是从新系统启动并在开机扫描时读到新 APK。两者都可以避免在已经显示的旧 Home 上原地换包，但机制不同。

## Framework 的设计支撑

- **安装侧的多层状态**：system copy（只读分区）+ data override（可写）+ staged 会话（待重启应用）；A/B OTA 另在系统分区槽位/快照层切换 system copy，不是第四个 `/data/app` 副本；
- **Home 角色抽象**：intent 解析 + `ROLE_HOME` 角色默认值，把"哪个包当桌面"与"哪个 APK 版本生效"解耦；
- **开机顺序的两种机制**：含 APEX 的 staged 会话先由 `apexd` 激活 APEX，再由 PMS `systemReady` 恢复会话、`StagingManager` 验证 APEX 状态并安装 APK，最终在 `PHASE_BOOT_COMPLETED` 标记成功；A/B OTA 在重启前已准备好新槽位或快照，重启后走新系统的普通开机扫描；
- **校验点**：安装时校验当前签名或 signing lineage capability；系统图像 priv-app 在开机时校验 allowlist，updated system app 的 privileged/OEM permission 另外受原系统副本的请求与授权基线限制。

## 源码入口（固定 revision）

frameworks/base 均为 `1cdfff555f4a21f71ccc978290e2e212e2f8b168`，SHA-256 与断言见证据包；仅 RoleManager 来自 Permission 模块（`26231a7eac744c7d2a8fea4740926620f56b20c6`）：

- [StagingManager.java](https://android.googlesource.com/platform/frameworks/base/+/1cdfff555f4a21f71ccc978290e2e212e2f8b168/services/core/java/com/android/server/pm/StagingManager.java)：staged 会话生命周期；确认 APEX 已由 `apexd` 激活后安装 APK 部分，并在 boot phase 收尾；
- [PackageManagerService.java](https://android.googlesource.com/platform/frameworks/base/+/1cdfff555f4a21f71ccc978290e2e212e2f8b168/services/core/java/com/android/server/pm/PackageManagerService.java)：systemReady 末尾触发 staged 会话恢复；
- [InstallPackageHelper.java](https://android.googlesource.com/platform/frameworks/base/+/1cdfff555f4a21f71ccc978290e2e212e2f8b168/services/core/java/com/android/server/pm/InstallPackageHelper.java)：更新路径上禁用系统副本、冻结被替换包；
- [BroadcastHelper.java](https://android.googlesource.com/platform/frameworks/base/+/1cdfff555f4a21f71ccc978290e2e212e2f8b168/services/core/java/com/android/server/pm/BroadcastHelper.java)：`ACTION_PACKAGE_REPLACED` 与杀进程决策；
- [Settings.java](https://android.googlesource.com/platform/frameworks/base/+/1cdfff555f4a21f71ccc978290e2e212e2f8b168/services/core/java/com/android/server/pm/Settings.java)：`disableSystemPackageLPw` 与 disabled 集合；
- [ScanPackageUtils.java](https://android.googlesource.com/platform/frameworks/base/+/1cdfff555f4a21f71ccc978290e2e212e2f8b168/services/core/java/com/android/server/pm/ScanPackageUtils.java)：updated system app 标记；
- [ComputerEngine.java](https://android.googlesource.com/platform/frameworks/base/+/1cdfff555f4a21f71ccc978290e2e212e2f8b168/services/core/java/com/android/server/pm/ComputerEngine.java)：`getHomeActivitiesAsUser` / `getDefaultHomeActivity`；
- [PackageInstaller.java](https://android.googlesource.com/platform/frameworks/base/+/1cdfff555f4a21f71ccc978290e2e212e2f8b168/core/java/android/content/pm/PackageInstaller.java)：`setStaged()` API；
- [PackageManager.java](https://android.googlesource.com/platform/frameworks/base/+/1cdfff555f4a21f71ccc978290e2e212e2f8b168/core/java/android/content/pm/PackageManager.java)：`INSTALL_FAILED_UPDATE_INCOMPATIBLE` 与 `getHomeActivities`；默认 Home 的持久化不在此 API（见 ComputerEngine 与 RoleManager）。
- [SystemConfig.java](https://android.googlesource.com/platform/frameworks/base/+/1cdfff555f4a21f71ccc978290e2e212e2f8b168/services/core/java/com/android/server/SystemConfig.java)：privapp-permissions 白名单解析；
- [PackageManagerServiceUtils.java](https://android.googlesource.com/platform/frameworks/base/+/1cdfff555f4a21f71ccc978290e2e212e2f8b168/services/core/java/com/android/server/pm/PackageManagerServiceUtils.java)：updated system app 与预装副本的签名 lineage/capability 校验；
- [AppIdPermissionPolicy.kt](https://android.googlesource.com/platform/frameworks/base/+/1cdfff555f4a21f71ccc978290e2e212e2f8b168/services/permission/java/com/android/server/permission/access/permission/AppIdPermissionPolicy.kt)：priv-app allowlist 的开机强制与 updated system app 权限基线；
- [RoleManager.java](https://android.googlesource.com/platform/packages/modules/Permission/+/26231a7eac744c7d2a8fea4740926620f56b20c6/framework-s/java/android/app/role/RoleManager.java)：`ROLE_HOME` 角色常量。
- [A/B 无缝系统更新](https://source.android.com/docs/core/ota/ab)：legacy A/B 的 `update_engine`、非当前槽位、bootloader 切换与回退边界；
- [Virtual A/B overview](https://source.android.com/docs/core/ota/virtual_ab)：Virtual A/B 对物理分区使用新槽位、对动态分区使用 Android COW 快照及后续合并的官方边界。

## 设备上的只读验证

```bash
# 更新前/后：codePath、版本、是否系统包
adb shell pm path <pkg>                    # 出现 /data/app/... 说明存在 data override
adb shell dumpsys package <pkg> | grep -E 'codePath|versionName|versionCode'

# Home 解析：更新后是否仍为默认 Home
adb shell cmd package resolve-activity --brief \
  -a android.intent.action.MAIN \
  -c android.intent.category.HOME

# 指定/核对默认 Home（Android 10+）
adb shell cmd role add-role-holder android.app.role.HOME <pkg>

# 回滚兜底
adb shell pm rollback-app <pkg>

# staged 安装（示意，实际参数以当前版本文档为准）
adb install --staged <apk>
```

这些命令回答"装在哪、谁生效、谁是 Home"；"首帧已合成、可交互"仍需 Perfetto 与 SurfaceFlinger/输入观测，同 [Home/SystemUI 文档](Home-Launcher-SystemUI-%E8%BF%9B%E7%A8%8B%E4%B8%8EAPK%E8%BE%B9%E7%95%8C.md) 的边界。

## 待验证清单

已由证据包断言的机制不在此列；以下仍待后续核对：

- [ ] 系统副本移入 `mDisabledSysPackages` 后，其组件级 disable 状态的确切设置时点；
- [ ] staged 会话从 commit/markReady 到重启后 restore 的完整中间链（已断言两端：`commitSession` 与 `restoreAndApplyStagedSessionIfNeeded`）；
- [ ] staging 目录的确切路径（当前 revision 的已断言文件中未出现该路径常量）；
- [ ] 开机扫描时 data override 相对 system copy 的优先级规则（"重启后依然生效"的推断依据，未直接断言）；
- [ ] `ROLE_HOME` 默认值的持久化位置与 `DefaultAppProvider` 的实现细节；
- [ ] `INSTALL_DONT_KILL_APP` 未设置时杀旧进程的实际执行点（已断言 `killApp` 计算与 PackageFreezer 冻结两端）。
- [ ] 目标产品的签名轮换方案（platform/shared UID/signature permission）与 CTS/存量设备兼容性。

## 继续阅读

- [系统应用更新与 OTA 证据包](../../../evidence/android/framework/system-app-update/manifest.json)：本文关键结论的固定源码、SHA-256 与可执行断言；
- [Android Framework 高频核心讲义](Android-Framework-%E9%AB%98%E9%A2%91%E6%A0%B8%E5%BF%83%E8%AE%B2%E4%B9%89.md)：第 10 章（PackageManager 与安装）、第 11 章（权限、签名、SELinux）是本文的基础；
- [Home、Launcher 与 SystemUI：进程与 APK 边界](Home-Launcher-SystemUI-%E8%BF%9B%E7%A8%8B%E4%B8%8EAPK%E8%BE%B9%E7%95%8C.md)：Home 角色模型与 APK 边界的事实源；
- [系统更新UI与Home无缝切换](%E7%B3%BB%E7%BB%9F%E6%9B%B4%E6%96%B0UI%E4%B8%8EHome%E6%97%A0%E7%BC%9D%E5%88%87%E6%8D%A2.md)：运行态更新幕布、最小权限候选架构、首帧交接与回滚状态机；
- [Android 建设路线](../ROADMAP.md)：第三阶段「Runtime、安全与工程诊断」（其中包含包管理、权限、签名）与本主题的规划关系。
