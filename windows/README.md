# Vertex 口袋网关 · Windows

Windows 10/11 64 位免安装桌面版。双击 `VertexPocketPC.exe` 即可运行，无需 Python、Java、Termux 或 Magpie。

## 使用方法

1. 解压下载包，双击 `VertexPocketPC.exe`。
2. 选择“服务账号 JSON”，导入 Google Cloud 服务账号 JSON 密钥，项目 ID 自动填写。
3. 确认区域和模型名称。默认区域为 `global`，模型列表按你的项目实际可用型号修改，用英文逗号分隔。
4. 复制应用生成的本地访问 Key。也可以自行设置，至少 8 位，不含空格的英文、数字或符号。
5. 可先点击“检测 Google 凭据”，这只申请短期访问令牌，不生成模型回复；模型访问权限和计费仍需实际聊天确认。
6. 点击“保存并启动”。
7. 在 Chatbox、SillyTavern 等软件中选择 OpenAI 兼容接口，填写：

| 设置 | 内容 |
| --- | --- |
| Base URL | `http://127.0.0.1:3425/v1` |
| API Key | 本应用中复制的本地访问 Key |
| 模型 | 模型列表中的一个型号，以 Google 项目实际可用型号为准 |

端口可修改；修改后使用界面中显示的新地址。如果软件自动添加 `/v1`，避免重复。如果它要求完整聊天接口，则追加 `/chat/completions`。

## 两种认证方式

**服务账号 JSON：** 使用私钥在本机签名，向 Google 申请通常约一小时有效的访问令牌。请求时若距离过期不足两分钟会自动重新申请；Google 返回 401 时会刷新并重试一次，不需要每小时手动换令牌。

**临时 Access Token：** 直接粘贴已有令牌，不要带 `Bearer ` 前缀；项目 ID 需手动填写。令牌不能自行续期，过期后请先停止服务，粘贴新的令牌，再启动。此模式的“检测凭据”只提示验证方法，实际有效性需发起模型请求确认。

聊天软件填写的本地访问 Key 与 Google 令牌是两回事，本地 Key 不会跟随一小时到期。

## 数据与运行方式

- 只监听 `127.0.0.1`，供同一台电脑上的软件使用，不向局域网开放。
- 凭据和连接设置经 Windows 当前账号的 DPAPI 加密后保存在 `%LOCALAPPDATA%\VertexPocketPC\settings.bin`。复制到其他 Windows 账号或电脑不能直接使用。运行中的同账号程序仍可能读取你的应用数据，DPAPI 不能防御已被攻破的用户会话。
- 原始 JSON 不会发到第三方服务。应用直接向 Google 认证并转发模型调用。原始密钥文件不由本应用删除。
- 最小化窗口后继续运行；关闭窗口退出会停止网关。电脑睡眠、关机和退出登录会影响连接。本版不含开机自启和托盘图标。
- 使用 Windows 系统代理配置和环境代理配置（由 Python urllib 读取），不包含内置 VPN 或代理服务。
- Google Cloud 项目需启用 Vertex AI API、有效计费，并给予服务账号对应模型的调用权限。调用由 Google 按项目计费。
- 可用模型和区域由 Google 项目决定；本地模型列表只是手工配置清单，不是实时权限查询结果。

## 支持范围

- `GET /v1/models`、`POST /v1/chat/completions`，包括 SSE 流式回复。
- 请求需携带 `Authorization: Bearer <本地访问 Key>`。
- 聊天请求参数转发给 Google OpenAI 兼容接口；模型、工具调用、多模态等参数能否使用取决于上游支持范围。未实现 Responses、独立 embeddings、文件上传等接口。
- 请求体最大 8 MB，最多同时处理 8 个连接，请求需带单个 Content-Length，不支持 chunked 请求体。
- 上游网络操作超时为 180 秒；停止服务时关闭本地连接，上游正在等待的数据读取可能在超时后才释放，但不会阻止退出程序。
- EXE 未使用付费 Windows 代码签名证书签名。

## 常见问题

- 启动失败：检查端口是否被占用，也不要同时运行多个使用同一端口的网关。
- 本地 401：聊天软件中的本地访问 Key 不一致。
- Google 401：临时令牌可能已过期；JSON 模式请检查密钥和电脑时间。
- Google 403：检查 API、计费、服务账号权限和模型访问权限。
- Google 400/404：检查模型名称、区域和聊天软件的参数。
- 连不上 Google：检查电脑网络及系统代理是否能访问 Google OAuth 与 Vertex AI 接口。

## 验证状态

17 项本机模拟测试通过，覆盖 JWT 签名与令牌缓存/到期更新、本地鉴权、模型列表、区域地址、中文聊天、实时流式转发、401 刷新重试、上游错误、无效请求、停止服务和 Windows DPAPI 加密保存。

最终打包 EXE 也已通过隐藏界面检查：创建界面、切换认证模式、生成 Key、启动模型列表接口、加密保存及停止服务。测试只使用临时假凭据，未访问用户真实配置或调用 Google 模型。尚未完成真实 Google 账号的端到端验证。

## 从源码运行或打包

在 Windows 上安装 Python 3.13 64 位。在本目录运行：

```powershell
python -m pip install --target _deps -r requirements.txt
$env:PYTHONPATH = "$PWD\_deps"
python app.py
```

打包：`python build.py`，产物在 `dist/VertexPocketPC.exe`。

测试：`python -m unittest test_gateway -v`（保持上述 PYTHONPATH 设置）。测试使用本机 23425 端口和模拟 Google 响应，不调用真实 Google 服务。

桌面界面和成品检查：`dist\VertexPocketPC.exe --ui-smoke-test "$PWD\smoke-result.json"`，使用本机 23426 端口，结果保存到指定文件。
