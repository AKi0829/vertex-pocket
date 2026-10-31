"""Loopback-only Vertex gateway. No cloud relay and no credential logging."""
import base64
import copy
import hmac
import json
import re
import socket
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa


def validate_credentials(data):
    if not isinstance(data, dict) or data.get('type') != 'service_account':
        raise ValueError('请选择 service_account 类型的 Google JSON 密钥。')
    if not data.get('client_email') or not data.get('project_id'):
        raise ValueError('JSON 缺少服务账号邮箱或项目 ID。')
    key = serialization.load_pem_private_key(data.get('private_key', '').encode(), None)
    if not isinstance(key, rsa.RSAPrivateKey):
        raise ValueError('需要 RSA 服务账号私钥。')
    return key


def validate_config(config):
    if not re.fullmatch(r'[a-z][a-z0-9-]{4,61}[a-z0-9]', config['project']):
        raise ValueError('请填写正确的 Google Cloud 项目 ID。')
    if not re.fullmatch(r'[a-z][a-z0-9-]{1,40}', config['region']):
        raise ValueError('区域格式不正确，例如 global 或 us-central1。')
    key = config['key']
    if len(key) < 8 or key != key.strip() or any(ord(c) < 33 or ord(c) > 126 for c in key):
        raise ValueError('本地访问 Key 至少 8 位，请使用不含空格的英文字母、数字或符号。')
    if not config['models']:
        raise ValueError('请至少填写一个模型。')
    if not 1024 <= int(config['port']) <= 65535:
        raise ValueError('端口须为 1024～65535。')
    if config['mode'] == 'json':
        validate_credentials(config.get('credentials'))
    elif config['mode'] == 'token':
        token = config.get('token', '')
        if not token or any(ord(c) <= 32 or ord(c) > 126 for c in token):
            raise ValueError('请粘贴有效的 Google Access Token，不要带 Bearer 前缀。')
    else:
        raise ValueError('请选择认证方式。')


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def google_open(request, timeout):
    # Keep normal system proxy and TLS certificate verification; forbid redirects.
    return urllib.request.build_opener(NoRedirect()).open(request, timeout=timeout)


class GoogleAuth:
    def __init__(self, config, opener=google_open):
        self.mode = config['mode']
        self.credentials = config.get('credentials')
        self.manual = config.get('token', '')
        self.open = opener
        self.cached = None
        self.expires = 0
        self.lock = threading.Lock()
        self.signer = validate_credentials(self.credentials) if self.mode == 'json' else None

    def invalidate(self):
        with self.lock:
            self.cached = None

    def token(self):
        if self.mode == 'token':
            return self.manual
        with self.lock:
            now = int(time.time())
            if self.cached and now < self.expires - 120:
                return self.cached
            def b64(value):
                return base64.urlsafe_b64encode(value).rstrip(b'=').decode('ascii')
            def encoded(value):
                return b64(json.dumps(value, separators=(',', ':')).encode())
            header = {'alg': 'RS256', 'typ': 'JWT'}
            claim = {'iss': self.credentials['client_email'], 'scope': 'https://www.googleapis.com/auth/cloud-platform',
                     'aud': 'https://oauth2.googleapis.com/token', 'iat': now, 'exp': now + 3600}
            unsigned = encoded(header) + '.' + encoded(claim)
            jwt = unsigned + '.' + b64(self.signer.sign(unsigned.encode(), padding.PKCS1v15(), hashes.SHA256()))
            body = urllib.parse.urlencode({'grant_type': 'urn:ietf:params:oauth:grant-type:jwt-bearer', 'assertion': jwt}).encode()
            req = urllib.request.Request('https://oauth2.googleapis.com/token', data=body,
                                         headers={'Content-Type': 'application/x-www-form-urlencoded'})
            try:
                with self.open(req, timeout=30) as response:
                    reply = json.loads(response.read(1024 * 1024))
            except urllib.error.HTTPError as exc:
                code = exc.code
                exc.close()
                raise ValueError(f'Google 认证失败 HTTP {code}，请检查密钥、电脑时间和账号状态。') from None
            self.cached = reply['access_token']
            self.expires = now + int(reply.get('expires_in', 3600))
            return self.cached


class Gateway:
    def __init__(self, config, log=lambda message: None, opener=google_open, auth=None):
        validate_config(config)
        self.config = copy.deepcopy(config)
        self.log = log
        self.open = opener
        self.auth = auth or GoogleAuth(config, opener)
        self.stopping = threading.Event()
        self.active = set()
        self.active_lock = threading.Lock()
        self.slots = threading.BoundedSemaphore(8)
        self.server = None

    def start(self):
        gateway = self
        class Server(ThreadingHTTPServer):
            daemon_threads = True
            allow_reuse_address = False
            def process_request(self, request, address):
                if not gateway.slots.acquire(False):
                    try:
                        request.sendall(b'HTTP/1.1 503 Busy\r\nContent-Length: 0\r\nConnection: close\r\n\r\n')
                    finally:
                        self.shutdown_request(request)
                    return
                with gateway.active_lock:
                    gateway.active.add(request)
                try:
                    super().process_request(request, address)
                except Exception:
                    with gateway.active_lock:
                        gateway.active.discard(request)
                    gateway.slots.release()
                    raise
            def process_request_thread(self, request, address):
                try:
                    super().process_request_thread(request, address)
                finally:
                    with gateway.active_lock:
                        gateway.active.discard(request)
                    gateway.slots.release()
            def handle_error(self, request, address):
                pass
        class Handler(BaseHTTPRequestHandler):
            protocol_version = 'HTTP/1.1'
            def setup(self):
                super().setup()
                self.connection.settimeout(30)
                self.responded = False
            def log_message(self, *args):
                pass
            def send_headers(self, code, content_type, length=None):
                self.responded = True
                self.send_response(code)
                self.send_header('Content-Type', content_type)
                self.send_header('Connection', 'close')
                self.send_header('Cache-Control', 'no-store')
                self.send_header('Access-Control-Allow-Origin', '*')
                self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
                self.send_header('Access-Control-Allow-Headers', 'Authorization, Content-Type')
                if length is not None:
                    self.send_header('Content-Length', str(length))
                self.end_headers()
                self.close_connection = True
            def reply(self, code, data):
                raw = json.dumps(data, ensure_ascii=False).encode('utf-8')
                self.send_headers(code, 'application/json; charset=utf-8', len(raw))
                self.wfile.write(raw)
                self.wfile.flush()
            def error(self, code, message):
                self.reply(code, {'error': {'message': message, 'type': 'gateway_error'}})
            def authorized(self):
                values = self.headers.get_all('Authorization') or []
                expected = 'Bearer ' + gateway.config['key']
                if len(values) != 1 or not hmac.compare_digest(values[0].encode('utf-8'), expected.encode('utf-8')):
                    self.error(401, '本地访问 Key 不正确。')
                    return False
                return True
            def do_OPTIONS(self):
                self.send_headers(204, 'text/plain', 0)
            def do_GET(self):
                if not self.authorized():
                    return
                if urllib.parse.urlsplit(self.path).path != '/v1/models':
                    self.error(404, '仅支持 /v1/models 和 /v1/chat/completions。')
                    return
                self.reply(200, {'object': 'list', 'data': [{'id': m, 'object': 'model', 'created': 0, 'owned_by': 'google'} for m in gateway.config['models']]})
            def do_POST(self):
                if not self.authorized():
                    return
                if urllib.parse.urlsplit(self.path).path != '/v1/chat/completions':
                    self.error(404, '不支持该接口，请使用 /v1/chat/completions。')
                    return
                try:
                    sizes = self.headers.get_all('Content-Length') or []
                    if len(sizes) != 1 or self.headers.get('Transfer-Encoding'):
                        self.error(411, '请用单个 Content-Length 发送请求。')
                        return
                    size = int(sizes[0])
                    if not 0 < size <= 8 * 1024 * 1024:
                        self.error(413, '请求体须为 1 字节至 8 MB。')
                        return
                    raw = self.rfile.read(size)
                    if len(raw) != size:
                        raise ValueError('请求体不完整。')
                    data = json.loads(raw)
                    if not isinstance(data, dict) or not isinstance(data.get('messages'), list):
                        raise ValueError('messages 必须为数组。')
                    model = data.get('model')
                    if not isinstance(model, str) or not model.strip():
                        raise ValueError('请填写模型名。')
                    if not isinstance(data.get('stream', False), bool):
                        raise ValueError('stream 必须为 true 或 false。')
                    model = model.strip()
                    data['model'] = model if '/' in model else 'google/' + model
                except (ValueError, UnicodeError, TypeError):
                    self.error(400, '请求 JSON、模型名、messages 或请求长度不正确。')
                    return
                try:
                    region = gateway.config['region']
                    host = 'aiplatform.googleapis.com' if region == 'global' else region + '-aiplatform.googleapis.com'
                    url = f'https://{host}/v1/projects/{gateway.config["project"]}/locations/{region}/endpoints/openapi/chat/completions'
                    for attempt in range(2):
                        token = gateway.auth.token()
                        if gateway.stopping.is_set():
                            return
                        req = urllib.request.Request(url, data=json.dumps(data, ensure_ascii=False).encode(),
                            headers={'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json', 'Accept-Encoding': 'identity'})
                        try:
                            response = gateway.open(req, timeout=180)
                        except urllib.error.HTTPError as exc:
                            response = exc
                        with response:
                            code = response.code
                            if code == 401 and gateway.auth.mode == 'json' and attempt == 0:
                                gateway.auth.invalidate()
                                continue
                            if code == 401 and gateway.auth.mode == 'token':
                                self.error(401, 'Google 临时令牌已过期或无效。请停止服务，粘贴新的令牌再启动。临时令牌不能自动续期。')
                                return
                            stream = data.get('stream', False) and 200 <= code < 300
                            self.send_headers(code, 'text/event-stream; charset=utf-8' if stream else 'application/json; charset=utf-8')
                            while not gateway.stopping.is_set():
                                chunk = response.read1(16384)
                                if not chunk:
                                    break
                                self.wfile.write(chunk)
                                self.wfile.flush()
                            gateway.log(f'聊天请求完成 · HTTP {code}')
                            return
                except Exception as exc:
                    if not self.responded:
                        message = 'Google 认证失败，请检查密钥、时间和网络。' if isinstance(exc, ValueError) else '连接 Google 失败，请检查网络、代理和区域设置。'
                        self.error(502, message)
                    gateway.log('请求未完成，请检查客户端错误提示及网络。')
        self.server = Server(('127.0.0.1', self.config['port']), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={'poll_interval': 0.1}, daemon=True)
        self.thread.start()

    def stop(self):
        self.stopping.set()
        if self.server:
            self.server.shutdown()
            with self.active_lock:
                for connection in list(self.active):
                    try:
                        connection.shutdown(socket.SHUT_RDWR)
                    except OSError:
                        pass
                    connection.close()
            self.server.server_close()

