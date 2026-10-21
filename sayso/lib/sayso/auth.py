import time

from .transport import TransportError, post_form_json, query_string, unquote_plus


TOKEN_URL = "https://accounts.spotify.com/api/token"
AUTHORIZE_URL = "https://accounts.spotify.com/authorize"


class SpotifyAuthError(Exception):
    pass


class TokenCache:
    def __init__(self, path="tokens.json"):
        self.path = path

    def load(self):
        try:
            import json
        except ImportError:
            return {}

        try:
            with open(self.path) as file:
                return json.load(file)
        except OSError:
            return {}

    def save(self, data):
        try:
            import json
        except ImportError:
            return False

        with open(self.path, "w") as file:
            json.dump(data, file)

        return True

    def load_auth(self, auth):
        data = self.load()
        auth.access_token = data.get("access_token")
        auth.expires_at = data.get("expires_at", 0)

        if data.get("refresh_token") is not None:
            auth.refresh_token = data["refresh_token"]

        if data.get("redirect_uri") is not None:
            auth.redirect_uri = data["redirect_uri"]

        if data.get("scope") is not None and auth.scope is None:
            auth.scope = data["scope"]

        return auth

    def save_auth(self, auth):
        data = {
            "access_token": auth.access_token,
            "expires_at": auth.expires_at,
            "refresh_token": auth.refresh_token,
        }

        redirect_uri = getattr(auth, "redirect_uri", None)
        if redirect_uri is not None:
            data["redirect_uri"] = redirect_uri

        scope = getattr(auth, "scope", None)
        if scope is not None:
            if isinstance(scope, str):
                data["scope"] = scope
            else:
                data["scope"] = " ".join(scope)

        return self.save(data)


class ClientCredentialsAuth:
    def __init__(self, client_id, client_secret):
        self.client_id = client_id
        self.client_secret = client_secret
        self.access_token = None
        self.expires_at = 0

    def token(self):
        if self.access_token is None or time.time() >= self.expires_at:
            self.refresh()
        return self.access_token

    def refresh(self):
        data = post_oauth_token(
            self.client_id,
            self.client_secret,
            {"grant_type": "client_credentials"},
        )

        self.access_token = data["access_token"]
        self.expires_at = time.time() + int(data.get("expires_in", 0)) - 60
        return self.access_token


class AuthorizationCodeAuth:
    def __init__(
        self,
        client_id,
        client_secret,
        redirect_uri,
        scope=None,
        refresh_token=None,
        code_verifier=None,
        token_cache=None,
    ):
        self.client_id = client_id
        self.client_secret = client_secret
        self.redirect_uri = redirect_uri
        self.scope = scope
        self.refresh_token = refresh_token
        self.code_verifier = code_verifier
        self.token_cache = token_cache
        self.access_token = None
        self.expires_at = 0

        if self.token_cache is not None:
            self.token_cache.load_auth(self)

    def authorize_url(self, state=None, show_dialog=None, code_challenge=None, code_challenge_method=None):
        if code_challenge is None and self.code_verifier is not None:
            code_challenge = code_challenge_s256(self.code_verifier)
            code_challenge_method = "S256"

        return authorization_url(
            self.client_id,
            self.redirect_uri,
            scope=self.scope,
            state=state,
            show_dialog=show_dialog,
            code_challenge=code_challenge,
            code_challenge_method=code_challenge_method,
        )

    def token(self):
        if self.access_token is None or time.time() >= self.expires_at:
            self.refresh()
        return self.access_token

    def exchange_code(self, code):
        data = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": self.redirect_uri,
        }
        if self.code_verifier is not None:
            data["code_verifier"] = self.code_verifier

        return self._update_tokens(self._post_token(data))

    def exchange_callback_url(self, callback_url, expected_state=None):
        values = parse_callback_url(callback_url)
        state = values.get("state")

        if expected_state is not None and state != expected_state:
            raise SpotifyAuthError("OAuth state mismatch")

        error = values.get("error")
        if error is not None:
            raise SpotifyAuthError("OAuth callback error: " + error)

        code = values.get("code")
        if code is None:
            raise SpotifyAuthError("OAuth callback did not include a code")

        return self.exchange_code(code)

    def refresh(self):
        if self.refresh_token is None:
            raise SpotifyAuthError("A refresh_token or authorization code is required")

        return self._update_tokens(
            self._post_token(
                {
                    "grant_type": "refresh_token",
                    "refresh_token": self.refresh_token,
                }
            )
        )

    def _post_token(self, data):
        return post_oauth_token(self.client_id, self.client_secret, data)

    def _update_tokens(self, data):
        self.access_token = data["access_token"]
        self.expires_at = time.time() + int(data.get("expires_in", 0)) - 60

        if data.get("refresh_token") is not None:
            self.refresh_token = data["refresh_token"]

        if self.token_cache is not None:
            self.token_cache.save_auth(self)

        return self.access_token


def post_oauth_token(client_id, client_secret, data):
    try:
        return post_form_json(
            TOKEN_URL,
            data,
            headers={"Authorization": "Basic " + basic_token(client_id, client_secret)},
        )
    except TransportError as error:
        raise oauth_error_from_transport(error) from error


def oauth_error_from_transport(error):
    data = error.data
    if isinstance(data, dict):
        oauth_error = data.get("error")
        if oauth_error is not None:
            message = "Spotify OAuth error: " + str(oauth_error)
            description = data.get("error_description")
            if description:
                message += " (" + str(description) + ")"
            return SpotifyAuthError(message)

    if error.status is not None:
        return SpotifyAuthError("Spotify OAuth request failed with HTTP status {}".format(error.status))

    return SpotifyAuthError(str(error))


def authorization_url(
    client_id,
    redirect_uri,
    scope=None,
    state=None,
    show_dialog=None,
    code_challenge=None,
    code_challenge_method=None,
):
    query = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
    }
    add_query(query, "scope", join_scope(scope))
    add_query(query, "state", state)
    add_query(query, "show_dialog", bool_string(show_dialog))
    add_query(query, "code_challenge", code_challenge)
    add_query(query, "code_challenge_method", code_challenge_method)

    return AUTHORIZE_URL + "?" + query_string(query)


def parse_callback_url(callback_url):
    query = callback_url
    question = query.find("?")
    if question >= 0:
        query = query[question + 1:]

    fragment = query.find("#")
    if fragment >= 0:
        query = query[:fragment]

    values = {}
    if not query:
        return values

    for part in query.split("&"):
        if not part:
            continue

        equal = part.find("=")
        if equal < 0:
            key = part
            value = ""
        else:
            key = part[:equal]
            value = part[equal + 1:]

        values[unquote_plus(key)] = unquote_plus(value)

    return values


def generate_code_verifier(length=64):
    if length < 43 or length > 128:
        raise SpotifyAuthError("PKCE code verifier length must be between 43 and 128")

    random_bytes = random_bytes_for_verifier(length)
    verifier = base64_urlsafe(random_bytes)

    if len(verifier) < length:
        return generate_code_verifier(length)

    return verifier[:length]


def code_challenge_s256(code_verifier):
    try:
        import hashlib
    except ImportError:
        raise SpotifyAuthError("hashlib is required for PKCE S256 code challenges")

    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    return base64_urlsafe(digest)


def pkce_pair(length=64):
    verifier = generate_code_verifier(length)
    return verifier, code_challenge_s256(verifier)


def random_bytes_for_verifier(length):
    try:
        import os
        return os.urandom(length)
    except (AttributeError, ImportError):
        try:
            import urandom
            return bytes(urandom.getrandbits(8) for _ in range(length))
        except ImportError:
            raise SpotifyAuthError("A random byte source is required for PKCE code verifier generation")


def base64_urlsafe(data):
    try:
        import base64
    except ImportError:
        raise SpotifyAuthError("base64 is required for PKCE helpers")

    encoded = base64.b64encode(data).decode("ascii")
    encoded = encoded.rstrip("=")
    encoded = encoded.replace("+", "-")
    encoded = encoded.replace("/", "_")
    return encoded


def join_scope(scope):
    if scope is None:
        return None
    if isinstance(scope, str):
        return scope
    return " ".join(scope)


def bool_string(value):
    if value is None:
        return None
    if value:
        return "true"
    return "false"


def add_query(query, key, value):
    if value is not None:
        query[key] = value


def basic_token(client_id, client_secret):
    raw = (client_id + ":" + client_secret).encode("utf-8")

    try:
        import base64
        return base64.b64encode(raw).decode("ascii")
    except ImportError:
        import binascii
        return binascii.b2a_base64(raw).strip().decode("ascii")


DEFAULT_CONFIG_PATH = "sayso.local.json"
DEFAULT_TOKEN_CACHE_PATH = "tokens.json"
DEFAULT_REDIRECT_URI = "http://127.0.0.1:8080"


USER_PROFILE_SCOPES = (
    "user-read-email",
)

LIBRARY_READ_SCOPES = (
    "user-library-read",
)

LIBRARY_WRITE_SCOPES = (
    "user-library-modify",
)

PLAYLIST_READ_SCOPES = (
    "playlist-read-private",
)

PLAYLIST_WRITE_SCOPES = (
    "playlist-modify-private",
    "playlist-modify-public",
    "ugc-image-upload",
)

PLAYBACK_READ_SCOPES = (
    "user-read-playback-state",
    "user-read-currently-playing",
    "user-read-recently-played",
    "user-top-read",
)

PLAYBACK_WRITE_SCOPES = (
    "user-modify-playback-state",
)

FOLLOW_WRITE_SCOPES = (
    "user-follow-modify",
)

EXAMPLE_SCOPES = (
    USER_PROFILE_SCOPES
    + LIBRARY_READ_SCOPES
    + LIBRARY_WRITE_SCOPES
    + PLAYLIST_READ_SCOPES
    + PLAYLIST_WRITE_SCOPES
    + PLAYBACK_READ_SCOPES
    + PLAYBACK_WRITE_SCOPES
    + FOLLOW_WRITE_SCOPES
)


class SpotifyConfigError(SpotifyAuthError):
    pass


def load_config(path=None):
    config_path = path or DEFAULT_CONFIG_PATH

    try:
        import json
    except ImportError:
        raise SpotifyConfigError("json is required to load sayso.local.json")

    try:
        with open(config_path) as file:
            data = json.load(file)
    except OSError as error:
        raise SpotifyConfigError(
            "Create {} from sayso.local.json.example and add your Spotify app credentials".format(
                config_path
            )
        ) from error

    if not isinstance(data, dict):
        raise SpotifyConfigError("{} must contain a JSON object".format(config_path))

    return data


def save_config(data, path=None):
    config_path = path or DEFAULT_CONFIG_PATH

    try:
        import json
    except ImportError:
        return False

    with open(config_path, "w") as file:
        json.dump(data, file, indent=2)
        file.write("\n")

    return True


def config_available(path=None):
    try:
        config = load_config(path)
    except SpotifyConfigError:
        return False

    client_id = config.get("client_id")
    client_secret = config.get("client_secret")
    return bool(client_id and client_secret)


def credentials_from_config(config):
    client_id = config.get("client_id")
    client_secret = config.get("client_secret")

    if not client_id or not client_secret:
        raise SpotifyConfigError(
            "sayso.local.json must include client_id and client_secret"
        )

    return client_id, client_secret


def redirect_uri_from_config(config, cached=None):
    value = config.get("redirect_uri")
    if value:
        return value

    if cached is not None and cached.get("redirect_uri"):
        return cached["redirect_uri"]

    return DEFAULT_REDIRECT_URI


def scopes_from_config(config, cached=None):
    value = config.get("scopes")
    if value:
        if isinstance(value, str):
            return value.split()
        return list(value)

    if cached is not None:
        scope = cached.get("scope")
        if scope:
            if isinstance(scope, str):
                return scope.split()
            return list(scope)

    return list(EXAMPLE_SCOPES)


def token_cache_from_config(config):
    path = config.get("token_cache", DEFAULT_TOKEN_CACHE_PATH)
    return TokenCache(path)


def config_value(config, key, default=None):
    value = config.get(key)
    if value is None:
        return default
    return value


def auth_from_config(
    config_path=None,
    scope=None,
    authenticate_if_needed=True,
    auth_state="sayso",
):
    config = load_config(config_path)
    client_id, client_secret = credentials_from_config(config)
    cache = token_cache_from_config(config)
    cached = cache.load()
    redirect_uri = redirect_uri_from_config(config, cached)
    refresh_token = cached.get("refresh_token")

    if scope is None:
        scope = scopes_from_config(config, cached)

    if refresh_token:
        return AuthorizationCodeAuth(
            client_id,
            client_secret,
            redirect_uri,
            scope=scope,
            refresh_token=refresh_token,
            token_cache=cache,
        )

    if not authenticate_if_needed:
        raise SpotifyConfigError(
            "No refresh token in {}. Run an example to authenticate in the browser first.".format(
                cache.path
            )
        )

    code_verifier = generate_code_verifier()
    auth = AuthorizationCodeAuth(
        client_id,
        client_secret,
        redirect_uri,
        scope=scope,
        code_verifier=code_verifier,
        token_cache=cache,
    )
    authorize_with_local_server(
        auth,
        redirect_uri=redirect_uri,
        state=auth_state,
        message="Spotify authorization received. You can close this window.",
    )
    return auth


def authorize_with_local_server(
    auth,
    redirect_uri,
    state="sayso",
    message="Spotify authorization received. You can close this window.",
    open_browser=True,
):
    host, port = redirect_uri_host_port(redirect_uri)
    url = auth.authorize_url(state=state, show_dialog=True)

    print_authorize_instructions(url, redirect_uri, open_browser=open_browser)
    callback_url = wait_for_oauth_callback(host, port, message, redirect_uri)
    access_token = auth.exchange_callback_url(callback_url, expected_state=state)

    print()
    print("Authorization complete. Saved tokens for future runs.")
    return access_token


def print_authorize_instructions(url, redirect_uri, open_browser=True):
    print()
    print("=" * 72)
    print("Spotify login required")
    print("=" * 72)
    print()
    print("Complete these steps:")
    print("  1. Open the authorize URL below in your browser.")
    print("  2. Log in to Spotify and approve access.")
    print("  3. Leave this terminal running until the callback is received.")
    print()
    print("Authorize URL:")
    print(url)
    print()

    opened = False
    if open_browser and not running_on_wsl():
        opened = try_open_browser(url)

    if opened:
        print("Opened your browser automatically.")
    elif running_on_wsl():
        print("WSL cannot open a browser automatically.")
        print("Copy the authorize URL above into a browser on Windows.")
    else:
        print("Could not open a browser automatically.")
        print("Copy the authorize URL above into your browser.")

    print()
    print("Waiting for Spotify to redirect to {} ...".format(redirect_uri))
    print()


def try_open_browser(url):
    try:
        import webbrowser
    except ImportError:
        return False

    suppress_stderr = _stderr_suppressor()
    if suppress_stderr is None:
        try:
            return webbrowser.open(url)
        except Exception:
            return False

    old_stderr = suppress_stderr[0]
    devnull = suppress_stderr[1]
    try:
        try:
            return webbrowser.open(url)
        except Exception:
            return False
    finally:
        _restore_stderr(old_stderr, devnull)


def wait_for_oauth_callback(host, port, message, redirect_uri):
    try:
        from http.server import BaseHTTPRequestHandler, HTTPServer
    except ImportError:
        return wait_for_oauth_callback_socket(host, port, message, redirect_uri)

    class CallbackHandler(BaseHTTPRequestHandler):
        callback_url = None

        def do_GET(self):
            CallbackHandler.callback_url = "http://{}:{}{}".format(host, port, self.path)
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(message.encode("utf-8"))

        def log_message(self, format, *args):
            pass

    server = HTTPServer((host, port), CallbackHandler)

    try:
        server.handle_request()
    finally:
        server.server_close()

    if CallbackHandler.callback_url is None:
        raise SpotifyAuthError(
            "No OAuth callback was received at {}. "
            "If the browser could not reach localhost, copy the full redirect URL "
            "into sayso.local.json as callback_url and run "
            "examples/authorization_code_pkce_exchange.py.".format(redirect_uri)
        )

    return CallbackHandler.callback_url


def wait_for_oauth_callback_socket(host, port, message, redirect_uri):
    try:
        import socket as socket_mod
    except ImportError:
        try:
            import usocket as socket_mod
        except ImportError as error:
            raise SpotifyAuthError(
                "Interactive OAuth requires http.server or socket, which is not "
                "available on this runtime"
            ) from error

    callback_url = None
    addr = socket_mod.getaddrinfo(host, port)[0][-1]
    sock = socket_mod.socket()
    sock.setsockopt(socket_mod.SOL_SOCKET, socket_mod.SO_REUSEADDR, 1)
    sock.bind(addr)
    sock.listen(1)

    try:
        conn, _addr = sock.accept()
        try:
            request = conn.recv(2048)
            if request:
                first_line = request.split(b"\r\n", 1)[0]
                parts = first_line.split(b" ")
                if len(parts) >= 2:
                    path = parts[1].decode()
                    callback_url = "http://{}:{}{}".format(host, port, path)
            body = message.encode("utf-8")
            response = (
                "HTTP/1.0 200 OK\r\n"
                "Content-Type: text/plain\r\n"
                "Content-Length: {}\r\n"
                "\r\n"
            ).format(len(body)).encode() + body
            conn.send(response)
        finally:
            conn.close()
    finally:
        sock.close()

    if callback_url is None:
        raise SpotifyAuthError(
            "No OAuth callback was received at {}. "
            "If the browser could not reach localhost, copy the full redirect URL "
            "into sayso.local.json as callback_url and run "
            "examples/authorization_code_pkce_exchange.py.".format(redirect_uri)
        )

    return callback_url


def running_on_wsl():
    import os

    environ = getattr(os, "environ", None)
    if environ is not None and environ.get("WSL_DISTRO_NAME"):
        return True

    try:
        with open("/proc/version") as file:
            return "microsoft" in file.read().lower()
    except OSError:
        return False


def _stderr_suppressor():
    import os
    import sys

    try:
        devnull = open(os.devnull, "w")
    except OSError:
        return None

    return sys.stderr, devnull


def _restore_stderr(old_stderr, devnull):
    import sys

    sys.stderr = old_stderr
    devnull.close()


def redirect_uri_host_port(redirect_uri):
    if redirect_uri.startswith("http://"):
        rest = redirect_uri[7:]
        default_port = 80
    elif redirect_uri.startswith("https://"):
        rest = redirect_uri[8:]
        default_port = 443
    else:
        raise SpotifyAuthError("redirect_uri must start with http:// or https://")

    slash = rest.find("/")
    if slash >= 0:
        authority = rest[:slash]
    else:
        authority = rest

    if not authority:
        raise SpotifyAuthError("redirect_uri is missing a host")

    colon = authority.rfind(":")
    if colon >= 0:
        host = authority[:colon]
        port = int(authority[colon + 1:])
    else:
        host = authority
        port = default_port

    return host, port
