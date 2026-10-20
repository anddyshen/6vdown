# 6vdown Mobile · 安卓客户端

6vdown NAS 追剧与磁力推送的专属移动端（基于 Flutter / Android），完美配合群晖 / Linux Docker 服务端运行。

---

## 核心特性

1. **🔐 安全访问与 Token 防护**：
   - 适配公网端口转发环境，支持配置高强度 `X-API-Token`；
   - 令牌基于 Android KeyStore 硬件级别加密隔离存储。
2. **⚡ 内外网无感智能漫游**：
   - 支持同时配置【局域网地址】与【公网 DDNS 域名】；
   - 启动时毫秒级心跳探测，在家走局域网，出门走公网，用户无需手动切换。
3. **🔋 零常驻后台功耗**：
   - 周期性追剧巡检与 Emby 比对完全由家中 NAS 完成，手机客户端无需常驻后台保活。
4. **📋 前台生命周期剪贴板嗅探**：
   - 复制磁力链接切回 App 时，自动弹出推送抽屉，一键下发到 NAS 下载器。
5. **📲 接入系统“分享到 6vdown”**：
   - 在手机浏览器或聊天工具中选中磁链或影片标题，点系统分享即可直达。

---

## 快速编译与打包 APK

### 环境要求
- Flutter SDK >= 3.0.0
- Android SDK 平台工具 (API 21 - 34)

### 编译步骤
```bash
# 1. 进入 mobile 目录
cd mobile

# 2. 安装移动端依赖
flutter pub get

# 3. 本地调试运行（连接手机或模拟器）
flutter run

# 4. 构建正式发布版 APK（生成于 build/app/outputs/flutter-apk/app-release.apk）
flutter build apk --release
```

---

## PWA 零编译模式（手机浏览器即开即用）

如果您不想安装编译环境，Docker 服务端内建了标准的 **PWA 渐进式 Web 应用**：
1. 用手机浏览器打开 `http://<NAS的IP>:5080`；
2. 点击浏览器右上角菜单，选择 **「添加到主屏幕」** 或 **「安装应用」**；
3. 手机桌面将生成一个独立沉浸式全屏 App，直接畅享移动端追剧与推送。
