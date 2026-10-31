import base64
import copy
import http.client
import io
import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from gateway import Gateway, GoogleAuth, validate_config
from storage import save_config, load_config


class Response(io.BytesIO):
    def __init__(self, body, code=200):
        super().__init__(body)
        self.code = code


class GatewayTests(unittest.TestCase):
    def setUp(self):
        self.config = dict(mode='token', token='synthetic-token', project='test-project', region='global',
                           port=23425, key='synthetic-local-key', models=['gemini-test'])
        self.calls = []
        self.logs = []
        self.gateways = []

    def tearDown(self):
        for gateway in self.gateways:
            gateway.stop()

    def start(self, opener=None, auth=None, config=None):
        def default_open(req, timeout):
            self.calls.append(req)
            return Response(json.dumps({'choices': [{'message': {'content': '你好'}}]}, ensure_ascii=False).encode())
        gateway = Gateway(config or self.config, opener=opener or default_open, auth=auth, log=self.logs.append)
        gateway.start()
        self.gateways.append(gateway)
        return gateway

    def request(self, method='GET', path='/v1/models', body=None, key='synthetic-local-key', headers=None):
        connection = http.client.HTTPConnection('127.0.0.1', self.config['port'], timeout=3)
        values = {'Authorization': 'Bearer ' + key}
        values.update(headers or {})
        connection.request(method, path, body=body, headers=values)
        reply = connection.getresponse()
        result = reply.status, reply.read(), dict(reply.getheaders())
        connection.close()
        return result

    def body(self, **extra):
        return json.dumps(dict(model='gemini-test', messages=[{'role': 'user', 'content': '你好'}], **extra)).encode()

    def test_loopback_only(self):
        gateway = self.start()
        self.assertEqual(gateway.server.server_address[0], '127.0.0.1')

    def test_unauthorized_never_calls_google(self):
        self.start()
        self.assertEqual(self.request(key='wrong')[0], 401)
        self.assertEqual(self.calls, [])

    def test_models_are_configured_list(self):
        self.start()
        code, data, _ = self.request()
        self.assertEqual(code, 200)
        self.assertEqual(json.loads(data)['data'][0]['id'], 'gemini-test')

    def test_cors_preflight(self):
        self.start()
        code, _, headers = self.request('OPTIONS', key='')
        self.assertEqual(code, 204)
        self.assertEqual(headers['Access-Control-Allow-Origin'], '*')

    def test_unicode_chat_prefix_url_and_bearer(self):
        self.start()
        code, data, _ = self.request('POST', '/v1/chat/completions', self.body())
        self.assertEqual(code, 200)
        self.assertIn('你好', data.decode())
        req = self.calls[0]
        self.assertEqual(json.loads(req.data)['model'], 'google/gemini-test')
        self.assertEqual(req.get_header('Authorization'), 'Bearer synthetic-token')
        self.assertEqual(req.full_url, 'https://aiplatform.googleapis.com/v1/projects/test-project/locations/global/endpoints/openapi/chat/completions')
        self.assertNotIn('synthetic-token', ' '.join(self.logs))
        self.assertNotIn('synthetic-local-key', ' '.join(self.logs))

    def test_regional_endpoint(self):
        config = dict(self.config, region='us-central1')
        self.start(config=config)
        self.request('POST', '/v1/chat/completions', self.body())
        self.assertIn('https://us-central1-aiplatform.googleapis.com/', self.calls[0].full_url)

    def test_stream_arrives_before_upstream_finishes(self):
        release = threading.Event()
        class Stream(Response):
            def __init__(self):
                super().__init__(b'')
                self.part = 0
            def read1(self, size):
                self.part += 1
                if self.part == 1:
                    return b'data: {"choices":[]}\n\n'
                if self.part == 2:
                    release.wait(3)
                    return b'data: [DONE]\n\n'
                return b''
        self.start(opener=lambda req, timeout: Stream())
        connection = http.client.HTTPConnection('127.0.0.1', self.config['port'], timeout=2)
        try:
            connection.request('POST', '/v1/chat/completions', body=self.body(stream=True), headers={'Authorization': 'Bearer synthetic-local-key'})
            response = connection.getresponse()
            self.assertEqual(response.getheader('Content-Type'), 'text/event-stream; charset=utf-8')
            self.assertEqual(response.readline(), b'data: {"choices":[]}\n')
            self.assertFalse(release.is_set())
            release.set()
            self.assertIn(b'data: [DONE]', response.read())
        finally:
            release.set()
            connection.close()

    def test_upstream_permission_error_preserved(self):
        self.start(opener=lambda req, timeout: Response(b'{"error":{"message":"permission denied"}}', 403))
        code, body, _ = self.request('POST', '/v1/chat/completions', self.body())
        self.assertEqual(code, 403)
        self.assertIn(b'permission denied', body)

    def test_expired_manual_token_has_clear_error(self):
        self.start(opener=lambda req, timeout: Response(b'{}', 401))
        code, body, _ = self.request('POST', '/v1/chat/completions', self.body())
        self.assertEqual(code, 401)
        self.assertIn('不能自动续期', body.decode())

    def test_json_mode_401_refreshes_and_retries(self):
        class FakeAuth:
            mode = 'json'
            refreshes = 0
            def token(self):
                return 'synthetic-token'
            def invalidate(self):
                self.refreshes += 1
        auth = FakeAuth()
        calls = []
        def opener(req, timeout):
            calls.append(req)
            return Response(b'{}', 401 if len(calls) == 1 else 200)
        self.start(opener=opener, auth=auth)
        self.assertEqual(self.request('POST', '/v1/chat/completions', self.body())[0], 200)
        self.assertEqual((auth.refreshes, len(calls)), (1, 2))

    def test_malformed_and_invalid_messages(self):
        self.start()
        for raw in [b'{', b'{"model":"m","messages":"bad"}', b'{"model":"m","messages":[],"stream":"true"}']:
            self.assertEqual(self.request('POST', '/v1/chat/completions', raw)[0], 400)
        self.assertEqual(self.calls, [])

    def test_unknown_endpoint(self):
        self.start()
        self.assertEqual(self.request('POST', '/v1/responses', self.body())[0], 404)

    def test_body_limit(self):
        self.start()
        self.assertEqual(self.request('POST', '/v1/chat/completions', b'', headers={'Content-Length': str(9 * 1024 * 1024)})[0], 413)

    def test_bad_key_and_port_rejected(self):
        for changes in [{'key': 'too short'}, {'key': '含有中文字符的密码'}, {'port': 80}, {'region': '../evil'}]:
            with self.assertRaises(ValueError):
                validate_config(dict(self.config, **changes))

    def test_stop_closes_listener(self):
        gateway = self.start()
        gateway.stop()
        self.gateways.clear()
        with self.assertRaises(OSError):
            self.request()


class AuthAndStorageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.signer = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        cls.credentials = dict(type='service_account', project_id='test-project', client_email='test@example.invalid',
            private_key=cls.signer.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode())

    def test_jwt_signature_claims_caching_and_expiry(self):
        calls = []
        def opener(req, timeout):
            calls.append(req)
            return Response(b'{"access_token":"synthetic-token","expires_in":3600}')
        auth = GoogleAuth(dict(mode='json', credentials=self.credentials), opener=opener)
        self.assertEqual(auth.token(), 'synthetic-token')
        self.assertEqual(auth.token(), 'synthetic-token')
        self.assertEqual(len(calls), 1)
        import urllib.parse
        jwt = urllib.parse.parse_qs(calls[0].data.decode())['assertion'][0]
        first, second, third = jwt.split('.')
        decode = lambda s: base64.urlsafe_b64decode(s + '=' * (-len(s) % 4))
        self.signer.public_key().verify(decode(third), (first + '.' + second).encode(), padding.PKCS1v15(), hashes.SHA256())
        claims = json.loads(decode(second))
        self.assertEqual(claims['aud'], 'https://oauth2.googleapis.com/token')
        self.assertEqual(claims['exp'] - claims['iat'], 3600)
        auth.expires = int(time.time()) + 60
        auth.token()
        self.assertEqual(len(calls), 2)

    def test_windows_encryption_roundtrip(self):
        # Local temporary directory only, no real account data accessed.
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            path = Path(directory) / 'settings.bin'
            config = {'credentials': self.credentials, 'key': 'synthetic-local-key', 'token': 'synthetic-token'}
            save_config(config, path)
            raw = path.read_bytes()
            self.assertNotIn(b'synthetic-token', raw)
            self.assertNotIn(b'PRIVATE KEY', raw)
            self.assertEqual(load_config(path), config)


if __name__ == '__main__':
    unittest.main(verbosity=2)
