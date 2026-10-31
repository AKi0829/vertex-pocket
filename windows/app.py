"""Vertex Pocket for Windows: native Tk UI and a loopback-only gateway."""
import argparse
import http.client
import json
import queue
import secrets
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from gateway import Gateway, GoogleAuth, validate_credentials, validate_config
from storage import load_config, save_config


class App:
    def __init__(self, root, config_file=None):
        self.root = root
        self.config_file = config_file
        self.gateway = None
        self.busy = False
        self.events = queue.Queue()
        self.credentials = None
        self.editable = []
        root.title('Vertex 口袋网关 · Windows')
        root.geometry('760x830')
        root.minsize(670, 650)
        root.protocol('WM_DELETE_WINDOW', self.close)
        style = ttk.Style(root)
        style.theme_use('clam')
        style.configure('.', font=('Microsoft YaHei UI', 10))
        style.configure('Title.TLabel', font=('Microsoft YaHei UI', 22, 'bold'))
        style.configure('Hint.TLabel', foreground='#536375')
        style.configure('Status.TLabel', foreground='#14785c', font=('Microsoft YaHei UI', 11, 'bold'))
        main = ttk.Frame(root, padding=22)
        main.pack(fill='both', expand=True)
        ttk.Label(main, text='Vertex 口袋网关', style='Title.TLabel').pack(anchor='w')
        ttk.Label(main, text='导入凭据 → 点击启动 → 聊天软件连接本机接口', style='Hint.TLabel').pack(anchor='w', pady=(4, 16))
        self.vars = {name: tk.StringVar(value=value) for name, value in {
            'mode': 'json', 'project': '', 'region': 'global', 'port': '3425',
            'models': 'gemini-2.5-flash,gemini-2.5-pro', 'key': secrets.token_urlsafe(24), 'token': '',
        }.items()}
        auth_frame = ttk.LabelFrame(main, text=' ① Google 凭据 ', padding=12)
        auth_frame.pack(fill='x')
        modes = ttk.Frame(auth_frame)
        modes.pack(fill='x')
        for label, value in [('服务账号 JSON（自动续期）', 'json'), ('临时 Access Token（手动更新）', 'token')]:
            item = ttk.Radiobutton(modes, text=label, variable=self.vars['mode'], value=value, command=self.switch_mode)
            item.pack(side='left', padx=(0, 12))
            self.editable.append(item)
        self.json_frame = ttk.Frame(auth_frame)
        self.json_frame.pack(fill='x', pady=(10, 0))
        self.import_button = ttk.Button(self.json_frame, text='选择 Google JSON 密钥', command=self.import_json)
        self.import_button.pack(side='left')
        self.editable.append(self.import_button)
        self.import_label = ttk.Label(self.json_frame, text='尚未导入密钥', style='Hint.TLabel')
        self.import_label.pack(side='left', padx=12)
        self.token_frame = ttk.Frame(auth_frame)
        ttk.Label(self.token_frame, text='Google Access Token').pack(anchor='w')
        token = ttk.Entry(self.token_frame, textvariable=self.vars['token'], show='•')
        token.pack(fill='x', pady=4)
        self.editable.append(token)
        ttk.Label(self.token_frame, text='通常约 1 小时有效；不要带 Bearer 前缀，过期后需停止服务并粘贴新令牌。', style='Hint.TLabel', wraplength=640).pack(anchor='w')
        settings = ttk.LabelFrame(main, text=' ② 连接设置 ', padding=12)
        settings.pack(fill='x', pady=12)
        settings.columnconfigure(1, weight=1)
        self.row(settings, 0, 'Google 项目 ID', 'project')
        self.row(settings, 1, 'Vertex 区域', 'region')
        self.row(settings, 2, '本地端口', 'port')
        self.row(settings, 3, '模型（英文逗号分隔）', 'models')
        self.key_entry = self.row(settings, 4, '本地访问 Key', 'key', show='•')
        actions = ttk.Frame(settings)
        actions.grid(row=5, column=1, sticky='w', pady=4)
        ttk.Button(actions, text='复制 Key', command=lambda: self.copy(self.vars['key'].get())).pack(side='left')
        self.show_key = tk.BooleanVar(value=False)
        ttk.Checkbutton(actions, text='显示 Key', variable=self.show_key, command=lambda: self.key_entry.configure(show='' if self.show_key.get() else '•')).pack(side='left', padx=12)
        info = ttk.LabelFrame(main, text=' ③ 启动并连接 ', padding=12)
        info.pack(fill='x')
        controls = ttk.Frame(info)
        controls.pack(fill='x')
        self.start_button = ttk.Button(controls, text='保存并启动', command=self.start)
        self.start_button.pack(side='left')
        self.stop_button = ttk.Button(controls, text='停止服务', command=self.stop, state='disabled')
        self.stop_button.pack(side='left', padx=8)
        self.test_button = ttk.Button(controls, text='检测 Google 凭据', command=self.test_auth)
        self.test_button.pack(side='left')
        self.status = tk.StringVar(value='服务未启动')
        ttk.Label(info, textvariable=self.status, style='Status.TLabel').pack(anchor='w', pady=(10, 5))
        address = ttk.Frame(info)
        address.pack(fill='x')
        self.url = tk.StringVar()
        ttk.Entry(address, textvariable=self.url, state='readonly').pack(side='left', fill='x', expand=True)
        ttk.Button(address, text='复制地址', command=lambda: self.copy(self.url.get())).pack(side='left', padx=(8, 0))
        ttk.Label(info, text='聊天软件选择 OpenAI 兼容接口；API Key 填上面的本地 Key。窗口最小化后仍运行，退出程序会停止。', style='Hint.TLabel', wraplength=650).pack(anchor='w', pady=(8, 0))
        ttk.Label(main, text='Google 项目需启用 Vertex AI、有效计费和对应权限。模型列表为手工配置，调用按 Google 项目计费。凭据加密保存在当前 Windows 账号下。', style='Hint.TLabel', wraplength=690).pack(anchor='w', pady=12)
        self.logs = tk.Text(main, height=5, wrap='word', font=('Microsoft YaHei UI', 9), state='disabled', relief='flat', background='#eef2f6', padx=10, pady=6)
        self.logs.pack(fill='both', expand=True)
        self.vars['port'].trace_add('write', lambda *_: self.update_url())
        self.load()
        self.switch_mode()
        self.update_url()
        self.root.after(100, self.poll)

    def row(self, parent, n, label, name, **options):
        ttk.Label(parent, text=label).grid(row=n, column=0, sticky='w', padx=(0, 14), pady=6)
        entry = ttk.Entry(parent, textvariable=self.vars[name], **options)
        entry.grid(row=n, column=1, sticky='ew', pady=6)
        self.editable.append(entry)
        return entry

    def switch_mode(self):
        if self.vars['mode'].get() == 'json':
            self.token_frame.pack_forget()
            self.json_frame.pack(fill='x', pady=(10, 0))
        else:
            self.json_frame.pack_forget()
            self.token_frame.pack(fill='x', pady=(10, 0))

    def update_url(self):
        self.url.set('http://127.0.0.1:' + self.vars['port'].get() + '/v1')

    def load(self):
        try:
            config = load_config(self.config_file)
            self.credentials = config.get('credentials')
            for name, var in self.vars.items():
                if name in config:
                    value = config[name]
                    var.set(','.join(value) if isinstance(value, list) else str(value))
            if self.credentials:
                validate_credentials(self.credentials)
                self.import_label.configure(text='已载入加密保存的服务账号密钥')
        except Exception:
            self.log('无法读取之前保存的配置，请重新导入；原配置文件未被删除。')

    def config(self):
        result = {name: var.get().strip() for name, var in self.vars.items()}
        result['key'] = self.vars['key'].get()
        try:
            result['port'] = int(result['port'])
        except ValueError:
            raise ValueError('端口请输入数字。') from None
        result['models'] = list(dict.fromkeys(m.strip() for m in result['models'].split(',') if m.strip()))
        result['credentials'] = self.credentials if result['mode'] == 'json' else None
        if result['mode'] == 'json':
            result['token'] = ''
        validate_config(result)
        return result

    def import_json(self):
        filename = filedialog.askopenfilename(parent=self.root, title='选择 Google 服务账号 JSON', filetypes=[('JSON 文件', '*.json'), ('所有文件', '*.*')])
        if not filename:
            return
        try:
            path = Path(filename)
            if path.stat().st_size > 131072:
                raise ValueError('文件过大，请选择 Google 服务账号密钥 JSON。')
            data = json.loads(path.read_text(encoding='utf-8-sig'))
            validate_credentials(data)
            self.credentials = data
            self.vars['project'].set(data['project_id'])
            self.import_label.configure(text='已导入服务账号密钥（启动时加密保存）')
            self.log('JSON 导入成功，项目 ID 已自动填写。')
        except Exception:
            messagebox.showerror('导入失败', '请选择有效的 service_account JSON，其中需要包含 RSA 私钥、client_email 和 project_id。', parent=self.root)

    def set_busy(self, busy):
        self.busy = busy
        locked = busy or self.gateway is not None
        for widget in self.editable:
            widget.configure(state='disabled' if locked else 'normal')
        self.start_button.configure(state='disabled' if locked else 'normal')
        self.test_button.configure(state='disabled' if locked else 'normal')
        self.stop_button.configure(state='normal' if self.gateway is not None and not busy else 'disabled')

    def background(self, action, done):
        self.set_busy(True)
        def worker():
            try:
                value = action()
                self.events.put(('done', done, value, None))
            except Exception as exc:
                self.events.put(('done', done, None, exc))
        threading.Thread(target=worker, daemon=True).start()

    def start(self):
        if self.busy or self.gateway:
            return
        try:
            config = self.config()
        except Exception as exc:
            messagebox.showerror('请检查设置', str(exc), parent=self.root)
            return
        def action():
            save_config(config, self.config_file)
            gateway = Gateway(config, log=lambda m: self.events.put(('log', m)))
            try:
                gateway.start()
            except Exception:
                if gateway.server:
                    gateway.server.server_close()
                raise
            return gateway
        def done(value, error):
            if error:
                self.status.set('启动失败')
                messagebox.showerror('启动失败', '无法启动本地网关。请检查端口是否被占用，以及本地配置目录是否可写。', parent=self.root)
            else:
                self.gateway = value
                self.status.set('已启动 · 仅本机可连接')
                self.log('服务已启动：' + self.url.get())
            self.set_busy(False)
        self.background(action, done)

    def stop(self):
        if self.busy or not self.gateway:
            return
        gateway = self.gateway
        self.status.set('正在停止…')
        def done(value, error):
            self.gateway = None
            self.status.set('服务已停止')
            self.log('服务已停止。')
            self.set_busy(False)
        self.background(gateway.stop, done)

    def test_auth(self):
        if self.busy or self.gateway:
            return
        try:
            config = self.config()
        except Exception as exc:
            messagebox.showerror('请检查设置', str(exc), parent=self.root)
            return
        if config['mode'] == 'token':
            messagebox.showinfo('临时令牌模式', '临时令牌只能通过实际模型请求确认是否有效。启动服务后在聊天软件中测试；过期后需手动更换。', parent=self.root)
            return
        self.status.set('正在连接 Google…')
        def done(value, error):
            self.status.set('服务未启动')
            self.set_busy(False)
            if error:
                messagebox.showerror('检测失败', '未能获取 Google 访问令牌。请检查密钥、电脑时间、网络及系统代理设置。', parent=self.root)
            else:
                messagebox.showinfo('凭据可用', '已取得 Google 访问令牌，未生成模型回复。模型权限、区域及计费仍需实际聊天确认。', parent=self.root)
        self.background(lambda: bool(GoogleAuth(config).token()), done)

    def copy(self, text):
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        self.root.update_idletasks()
        self.log('已复制到剪贴板。')

    def log(self, message):
        self.logs.configure(state='normal')
        self.logs.insert('end', datetime.now().strftime('%H:%M:%S') + '  ' + message + '\n')
        if int(self.logs.index('end-1c').split('.')[0]) > 150:
            self.logs.delete('1.0', '50.0')
        self.logs.see('end')
        self.logs.configure(state='disabled')

    def poll(self):
        try:
            while True:
                event = self.events.get_nowait()
                if event[0] == 'log':
                    self.log(event[1])
                else:
                    _, callback, value, error = event
                    callback(value, error)
        except queue.Empty:
            pass
        self.root.after(100, self.poll)

    def close(self):
        if self.busy:
            messagebox.showinfo('请稍候', '当前操作尚未结束，请稍后退出。', parent=self.root)
            return
        if self.gateway:
            if not messagebox.askyesno('退出网关', '退出会停止本地服务，正在生成的回复会中断。确定退出？', parent=self.root):
                return
            self.gateway.stop()
        self.root.destroy()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--ui-smoke-test', type=Path)
    args = parser.parse_args()
    root = tk.Tk()
    if args.ui_smoke_test:
        # Separate data file, no saved user credentials read or written in this check.
        root.withdraw()
        app = App(root, args.ui_smoke_test.with_suffix('.settings.bin'))
        root.update_idletasks()
        app.vars['mode'].set('token')
        app.switch_mode()
        root.update_idletasks()
        app.vars['mode'].set('json')
        app.switch_mode()
        root.update_idletasks()
        report = {'status': 'ok', 'title': root.title(), 'default_url': app.url.get(), 'key_generated': len(app.vars['key'].get()) >= 8, 'widgets': len(app.editable), 'json_and_token_modes': True}
        app.vars['mode'].set('token')
        app.vars['project'].set('test-project')
        app.vars['token'].set('synthetic-smoke-token')
        app.vars['key'].set('synthetic-smoke-key')
        app.vars['port'].set('23426')
        app.start()
        deadline = time.monotonic() + 10
        while app.busy and time.monotonic() < deadline:
            root.update()
            time.sleep(0.02)
        if not app.gateway:
            raise RuntimeError('Packaged gateway failed to start')
        connection = http.client.HTTPConnection('127.0.0.1', 23426, timeout=3)
        connection.request('GET', '/v1/models', headers={'Authorization': 'Bearer synthetic-smoke-key'})
        response = connection.getresponse()
        report['packaged_models_endpoint'] = response.status == 200 and bool(json.loads(response.read())['data'])
        connection.close()
        report['encrypted_settings'] = load_config(app.config_file)['token'] == 'synthetic-smoke-token' and b'synthetic-smoke-token' not in app.config_file.read_bytes()
        app.stop()
        deadline = time.monotonic() + 10
        while app.busy and time.monotonic() < deadline:
            root.update()
            time.sleep(0.02)
        report['packaged_start_stop'] = not app.busy and app.gateway is None
        if not all(report[name] for name in ['packaged_models_endpoint', 'encrypted_settings', 'packaged_start_stop']):
            raise RuntimeError('Packaged smoke test failed')
        args.ui_smoke_test.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        app.config_file.unlink()
        root.destroy()
    else:
        App(root)
        root.mainloop()


if __name__ == '__main__':
    main()
