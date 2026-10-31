# Vertex 口袋网关

支持 Android 和 Windows 的本机网关：导入 Google 服务账号 JSON 密钥，即可让支持 OpenAI 兼容接口的聊天软件连接 Vertex AI。无需 Magpie 或 Termux。

## 下载

- [Android APK 初版](https://github.com/AKi0829/vertex-pocket/releases/tag/v1.0.0)
- [Windows 免安装桌面版](https://github.com/AKi0829/vertex-pocket/releases/tag/windows-v1.0.0)

Windows 版解压后双击 `VertexPocketPC.exe`，无需安装 Python 或 Java。支持服务账号 JSON 自动续期，也可粘贴临时 Access Token。源码、构建方式和详细说明见 [windows/](windows/README.md)。

## Android 使用

1. 安装 APK，打开“Vertex 口袋网关”。
2. 导入 Google 服务账号 JSON，确认自动识别的项目 ID。
3. 配置可用的区域和模型，复制应用生成的访问 Key。
4. 点击“保存并启动”。
5. 在聊天软件中选择 OpenAI 兼容接口，地址填写 `http://127.0.0.1:3425/v1`，API Key 填写上一步复制的 Key。

支持 Android 8.0 及以上，包含流式聊天、前台服务通知及 Google 短期令牌自动刷新。只监听本机地址。

Google Cloud 项目需开启 Vertex AI API、有效计费，并向服务账号授予模型调用权限。模型和区域按项目实际可用情况配置；模型列表为手工配置。模型调用按 Google 项目计费。

## 接口

- `GET /v1/models`：返回配置的模型列表。
- `POST /v1/chat/completions`：转发到 Google 的 OpenAI 兼容接口，支持 SSE。
- 请求使用 `Authorization: Bearer <本地访问 Key>`。

## 验证状态

已通过 Android 官方工具编译、APK v2/v3 签名校验和 14 项使用模拟凭据的 JVM 测试。尚未进行安卓真机和真实 Google 项目的端到端验证。

## 构建和详细说明

参见 [使用说明](使用说明.md)。源码位于 `src/`，构建入口为 `build.py`，测试入口为 `test.py`。运行环境需要 JDK、Python 和 Android 官方 Build Tools / Platform 35。

不要提交服务账号 JSON、访问 Key 或 APK 签名私钥。密钥保存在手机应用私有目录，禁用应用备份。后台运行可能受厂商电池管理限制，重启手机后需手动启动。

