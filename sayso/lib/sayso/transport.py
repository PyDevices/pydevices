API_BASE_URL = "https://api.spotify.com/v1"

# Resolved once here, never inside a function. On MicroPython json is an
# extensible built-in, so every `import json` searches the filesystem first,
# and a failing `from urllib.parse import ...` searches all of sys.path: on
# an ESP32-S3 each cost ~185 ms, several per API call (2026-09-25).
try:
    import json as _json
except ImportError:  # pragma: no cover
    _json = None

try:
    from urllib.parse import quote as _urllib_quote
    from urllib.parse import unquote as _urllib_unquote
except ImportError:
    _urllib_quote = None
    _urllib_unquote = None


class TransportError(Exception):
    def __init__(self, message, status=None, data=None, retry_after=None):
        self.args = (message,)
        self.status = status
        self.data = data
        # Seconds from a Retry-After header (429, 503), or None. Spotify's can
        # be hours: 38108 s once an app had gone over its limit.
        self.retry_after = retry_after


def _retry_after(response):
    headers = getattr(response, "headers", None)
    if headers is None:
        return None
    try:
        value = headers.get("retry-after")
        if value is None:
            value = headers.get("Retry-After")
        return int(value) if value is not None else None
    except (AttributeError, TypeError, ValueError):
        return None


def _find_requests():
    import sys

    # MicroPython's requests does a TLS handshake per request; keep the
    # connection open instead (see keepalive.py).
    if sys.implementation.name == "micropython":
        try:
            from .keepalive import Session

            return Session()
        except ImportError:
            pass

    try:
        import requests

        return requests
    except ImportError:
        pass

    try:
        import ssl
        import wifi
        import socketpool
        import adafruit_requests

        pool = socketpool.SocketPool(wifi.radio)
        return adafruit_requests.Session(pool, ssl.create_default_context())
    except ImportError:
        pass

    raise TransportError(
        "No HTTP client is available. Install the requests package, or on "
        "CircuitPython use wifi, socketpool, ssl, and adafruit_requests."
    )


requests = _find_requests()


def get_json(path_or_url, access_token=None, query=None, headers=None, base_url=API_BASE_URL):
    url = build_url(path_or_url, query=query, base_url=base_url)
    request_headers = {}

    if headers:
        request_headers.update(headers)
    if access_token is not None:
        request_headers["Authorization"] = "Bearer " + access_token

    response = requests.get(url, headers=request_headers)
    return response_json(response)


def get_bytes(path_or_url, access_token=None, query=None, headers=None, base_url=API_BASE_URL):
    url = build_url(path_or_url, query=query, base_url=base_url)
    request_headers = {}

    if headers:
        request_headers.update(headers)
    if access_token is not None:
        request_headers["Authorization"] = "Bearer " + access_token

    response = requests.get(url, headers=request_headers)
    return response_bytes(response)


def post_form_json(url, data, headers=None):
    request_headers = {"Content-Type": "application/x-www-form-urlencoded"}
    if headers:
        request_headers.update(headers)

    body = query_string(data)
    response = requests.post(url, data=body, headers=request_headers)
    return response_json(response)


def post_json(path_or_url, data=None, access_token=None, query=None, headers=None, base_url=API_BASE_URL):
    return request_json("POST", path_or_url, data, access_token, query, headers, base_url)


def put_json(path_or_url, data=None, access_token=None, query=None, headers=None, base_url=API_BASE_URL):
    return request_json("PUT", path_or_url, data, access_token, query, headers, base_url)


def delete_json(path_or_url, data=None, access_token=None, query=None, headers=None, base_url=API_BASE_URL):
    return request_json("DELETE", path_or_url, data, access_token, query, headers, base_url)


def put_body(path_or_url, body, content_type, access_token=None, query=None, headers=None, base_url=API_BASE_URL):
    return request_body("PUT", path_or_url, body, content_type, access_token, query, headers, base_url)


def request_json(method, path_or_url, data=None, access_token=None, query=None, headers=None, base_url=API_BASE_URL):
    url = build_url(path_or_url, query=query, base_url=base_url)
    request_headers = {}

    if headers:
        request_headers.update(headers)
    if access_token is not None:
        request_headers["Authorization"] = "Bearer " + access_token

    body = None
    if data is not None:
        request_headers["Content-Type"] = "application/json"
        body = json_dumps(data)

    response = http_request(method, url, body, request_headers)
    return response_json(response)


def request_body(method, path_or_url, body, content_type, access_token=None, query=None, headers=None, base_url=API_BASE_URL):
    url = build_url(path_or_url, query=query, base_url=base_url)
    request_headers = {"Content-Type": content_type}

    if headers:
        request_headers.update(headers)
    if access_token is not None:
        request_headers["Authorization"] = "Bearer " + access_token

    response = http_request(method, url, body, request_headers)
    return response_json(response)


def http_request(method, url, body, headers):
    method_name = method.lower()
    if body is None and method_name in ("post", "put", "patch", "delete"):
        if "Content-Length" not in headers:
            headers["Content-Length"] = "0"
        body = ""

    if hasattr(requests, method_name):
        request_method = getattr(requests, method_name)
        if body is None:
            return request_method(url, headers=headers)
        return request_method(url, data=body, headers=headers)

    if hasattr(requests, "request"):
        return requests.request(method, url, data=body, headers=headers)

    raise TransportError("HTTP {} is not supported by the current requests backend".format(method))


def response_json(response):
    data = None
    try:
        status = response_status(response)
        if status == 204:
            return None

        try:
            data = parse_response_json(response, status=status)
        except ValueError:
            if status is not None and (status < 200 or status >= 300):
                data = _response_error_data(response)
                raise TransportError("HTTP status {}".format(status), status, data, _retry_after(response))
            raise
    finally:
        close_response(response)

    if status is not None and (status < 200 or status >= 300):
        raise TransportError("HTTP status {}".format(status), status, data, _retry_after(response))

    return data


def response_bytes(response):
    try:
        status = response_status(response)
        data = read_response_bytes(response)
    finally:
        close_response(response)

    if status is not None and (status < 200 or status >= 300):
        raise TransportError("HTTP status {}".format(status), status, data, _retry_after(response))

    return data


def response_status(response):
    if hasattr(response, "status_code"):
        return response.status_code
    if hasattr(response, "status"):
        return response.status
    if hasattr(response, "code"):
        return response.code
    if hasattr(response, "getcode"):
        return response.getcode()
    return None


def read_response_text(response):
    if hasattr(response, "text"):
        return response.text

    if hasattr(response, "content"):
        content = response.content
        if not isinstance(content, str):
            content = content.decode("utf-8")
        return content

    if hasattr(response, "read"):
        data = response.read()
        if not isinstance(data, str):
            data = data.decode("utf-8")
        return data

    return ""


def read_response_bytes(response):
    if hasattr(response, "content"):
        content = response.content
        if isinstance(content, str):
            content = content.encode("utf-8")
        return content

    if hasattr(response, "read"):
        data = response.read()
        if isinstance(data, str):
            data = data.encode("utf-8")
        return data

    if hasattr(response, "text"):
        return response.text.encode("utf-8")

    return b""


def parse_response_json(response, status=None):
    if hasattr(response, "json"):
        try:
            return response.json()
        except ValueError:
            if _empty_response_body(response):
                return None
            if _successful_status(status):
                return None
            raise

    if hasattr(response, "text") or hasattr(response, "content") or hasattr(response, "read"):
        body = read_response_text(response)
        if not body or not body.strip():
            return None

        try:
            return json_loads(body)
        except ValueError:
            if _successful_status(status):
                return None
            raise

    return response


def _empty_response_body(response):
    body = read_response_text(response)
    return not body or not body.strip()


def _response_error_data(response):
    body = read_response_text(response)
    if not body or not body.strip():
        return None

    try:
        return json_loads(body)
    except ValueError:
        return body


def _successful_status(status):
    return status is not None and 200 <= status < 300


def close_response(response):
    if hasattr(response, "close"):
        response.close()
    elif hasattr(response, "deinit"):
        response.deinit()


def json_loads(data):
    if _json is None:
        raise TransportError("No JSON parser is available on this Python runtime")

    if not isinstance(data, str):
        data = data.decode("utf-8")

    return _json.loads(data)


def json_dumps(data):
    if _json is None:
        raise TransportError("No JSON serializer is available on this Python runtime")

    return _json.dumps(data)


def build_url(path_or_url, query=None, base_url=API_BASE_URL):
    if path_or_url.startswith("http://") or path_or_url.startswith("https://"):
        url = path_or_url
    else:
        url = base_url + path_or_url

    encoded = query_string(query)
    if encoded:
        return url + "?" + encoded
    return url


def query_string(query):
    if not query:
        return ""

    parts = []
    for key in query:
        value = query[key]
        if value is not None:
            parts.append(quote(key) + "=" + quote(value))
    return "&".join(parts)


def quote(value):
    value = str(value)

    if _urllib_quote is not None:
        return _urllib_quote(value, safe="")
    return simple_quote(value)


def unquote_plus(value):
    value = value.replace("+", " ")

    if _urllib_unquote is not None:
        return _urllib_unquote(value)
    return simple_unquote(value)


def simple_quote(value):
    safe = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_.~"
    encoded = []

    for char in value:
        if char in safe:
            encoded.append(char)
        else:
            for byte in char.encode("utf-8"):
                encoded.append("%{:02X}".format(byte))

    return "".join(encoded)


def simple_unquote(value):
    chunks = []
    index = 0
    length = len(value)

    while index < length:
        char = value[index]
        if char == "%" and index + 2 < length:
            hex_value = value[index + 1:index + 3]
            try:
                chunks.append(int(hex_value, 16))
                index += 3
                continue
            except ValueError:
                pass

        for byte in char.encode("utf-8"):
            chunks.append(byte)
        index += 1

    return bytes(chunks).decode("utf-8")
