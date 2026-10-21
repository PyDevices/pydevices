import unittest

from sayso.transport import TransportError, http_request, response_bytes, response_json


class _MicroPythonLikeResponse:
    def __init__(self, status_code, body=b""):
        self.status_code = status_code
        self._body = body
        self.closed = False

    @property
    def content(self):
        return self._body

    @property
    def text(self):
        if isinstance(self._body, str):
            return self._body
        return self._body.decode("utf-8")

    def json(self):
        import json

        return json.loads(self.content)

    def close(self):
        self.closed = True


class TransportResponseJsonTest(unittest.TestCase):
    def test_empty_success_body_returns_none(self):
        response = _MicroPythonLikeResponse(204, b"")
        self.assertIsNone(response_json(response))
        self.assertTrue(response.closed)

    def test_empty_error_body_raises_transport_error(self):
        response = _MicroPythonLikeResponse(404, b"")
        with self.assertRaises(TransportError) as context:
            response_json(response)

        self.assertEqual(context.exception.status, 404)
        self.assertIsNone(context.exception.data)

    def test_non_json_error_body_raises_transport_error(self):
        response = _MicroPythonLikeResponse(404, b"Player command failed: No active device found")
        with self.assertRaises(TransportError) as context:
            response_json(response)

        self.assertEqual(context.exception.status, 404)
        self.assertEqual(
            context.exception.data,
            "Player command failed: No active device found",
        )


class TransportResponseBytesTest(unittest.TestCase):
    def test_success_body_returns_bytes(self):
        response = _MicroPythonLikeResponse(200, b"\xff\xd8jpeg")
        self.assertEqual(response_bytes(response), b"\xff\xd8jpeg")
        self.assertTrue(response.closed)

    def test_text_body_is_encoded(self):
        response = _MicroPythonLikeResponse(200, "hello")
        self.assertEqual(response_bytes(response), b"hello")

    def test_error_status_raises_transport_error_with_body(self):
        response = _MicroPythonLikeResponse(404, b"missing")
        with self.assertRaises(TransportError) as context:
            response_bytes(response)

        self.assertEqual(context.exception.status, 404)
        self.assertEqual(context.exception.data, b"missing")


class TransportHttpRequestTest(unittest.TestCase):
    def test_bodyless_post_sets_content_length_zero(self):
        captured = {}

        def fake_post(url, data=None, headers=None):
            captured["url"] = url
            captured["data"] = data
            captured["headers"] = headers
            return _MicroPythonLikeResponse(204, b"")

        import sayso.transport as transport_module

        original_post = transport_module.requests.post
        transport_module.requests.post = fake_post
        try:
            http_request(
                "POST",
                "https://api.spotify.com/v1/me/player/next",
                None,
                {"Authorization": "Bearer token"},
            )
        finally:
            transport_module.requests.post = original_post

        self.assertEqual(captured["data"], "")
        self.assertEqual(captured["headers"]["Content-Length"], "0")


if __name__ == "__main__":
    unittest.main()
