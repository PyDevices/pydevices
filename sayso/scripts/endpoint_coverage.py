import argparse
import ast
import os

try:
    from generate_object_specs import DEFAULT_SCHEMA_URL, load_schema
except ImportError:
    from scripts.generate_object_specs import DEFAULT_SCHEMA_URL, load_schema


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_CLIENT_PATH = os.path.join(ROOT, "sayso", "client.py")

REQUEST_HELPERS = {
    "_get_json": "GET",
    "_put_json": "PUT",
    "_post_json": "POST",
    "_delete_json": "DELETE",
    "_put_body": "PUT",
    "_put_ids": "PUT",
    "_delete_ids": "DELETE",
    "_bools": "GET",
    "_follow": "PUT",
    "_unfollow": "DELETE",
    "_one": "GET",
    "_many": "GET",
    "_page": "GET",
}

TOP_TYPE_PATHS = {
    "/me/top/artists",
    "/me/top/tracks",
}


def main():
    parser = argparse.ArgumentParser(description="Compare SpotifyClient endpoint coverage to the OpenAPI schema.")
    parser.add_argument("--schema", default=DEFAULT_SCHEMA_URL, help="OpenAPI schema URL or local file path")
    parser.add_argument("--client", default=DEFAULT_CLIENT_PATH, help="Path to sayso/client.py")
    parser.add_argument("--map", action="store_true", help="Print the OpenAPI path to SpotifyClient method map")
    args = parser.parse_args()

    schema = load_schema(args.schema)
    client_endpoints = extract_client_endpoints(args.client)
    report = endpoint_coverage(schema, client_endpoints)

    print("openapi endpoints:", len(report["openapi"]))
    print("client endpoints:", len(report["client"]))
    print("covered endpoints:", len(report["covered"]))
    print("missing from client:", len(report["missing"]))
    print("client-only (not in schema):", len(report["extra"]))

    if report["missing"]:
        print()
        print("missing from client:")
        for method, path, operation_id in report["missing"]:
            label = operation_id or ""
            print(method, path, label)

    if report["extra"]:
        print()
        print("client-only (not in schema):")
        for method, path, client_methods in report["extra"]:
            print(method, path, format_methods(client_methods))

    if args.map or report["missing"]:
        print()
        print("openapi path -> SpotifyClient method(s):")
        for method, path, operation_id, client_methods in report["mapping"]:
            label = operation_id or ""
            print("{} {} -> {}  {}".format(method, path, format_methods(client_methods), label).rstrip())


def endpoint_coverage(schema, client_endpoints):
    openapi = openapi_endpoints(schema)
    openapi_keys = set((method, path) for method, path, operation_id in openapi)

    client_by_key = {}
    for method, path, client_method in client_endpoints:
        key = (method, path)
        client_by_key.setdefault(key, set()).add(client_method)

    client_keys = set(client_by_key)

    missing = []
    covered = []
    mapping = []

    for method, path, operation_id in openapi:
        client_methods = client_methods_for_openapi(client_by_key, method, path)
        if client_methods:
            covered.append((method, path, operation_id))
        else:
            missing.append((method, path, operation_id))
        mapping.append((method, path, operation_id, sorted(client_methods)))

    extra = []
    for key in sorted(client_keys - openapi_keys):
        extra.append((key[0], key[1], sorted(client_by_key[key])))

    return {
        "openapi": openapi,
        "client": tuple(sorted(client_keys)),
        "covered": tuple(covered),
        "missing": tuple(missing),
        "extra": tuple(extra),
        "mapping": tuple(mapping),
    }


def client_methods_for_openapi(client_by_key, method, path):
    direct = client_by_key.get((method, path), set())
    if direct:
        return direct

    if path == "/me/top/{type}":
        methods = set()
        for top_path in TOP_TYPE_PATHS:
            methods.update(client_by_key.get((method, top_path), set()))
        return methods

    return set()


def extract_client_endpoints(client_path):
    with open(client_path) as file:
        source = file.read()

    tree = ast.parse(source)
    endpoints = []
    wrapper_map = {}

    for node in tree.body:
        if not isinstance(node, ast.ClassDef) or node.name != "SpotifyClient":
            continue
        wrapper_map = build_wrapper_map(node)
        for item in node.body:
            if not isinstance(item, ast.FunctionDef):
                continue
            endpoints.extend(extract_method_endpoints(item))

    expanded = []
    for method, path, client_method in endpoints:
        expanded.append((method, path, client_method))
        if client_method.startswith("_"):
            for wrapper in sorted(wrapper_map.get(client_method, ())):
                expanded.append((method, path, wrapper))

    return tuple(sorted(set(expanded)))


def build_wrapper_map(class_node):
    wrappers = {}
    for item in class_node.body:
        if not isinstance(item, ast.FunctionDef):
            continue
        if item.name.startswith("_"):
            continue
        for node in ast.walk(item):
            if not isinstance(node, ast.Call):
                continue
            if not isinstance(node.func, ast.Attribute):
                continue
            if not isinstance(node.func.value, ast.Name) or node.func.value.id != "self":
                continue
            callee = node.func.attr
            if callee.startswith("_"):
                wrappers.setdefault(callee, set()).add(item.name)
    return wrappers


def extract_method_endpoints(method_node):
    endpoints = []

    for node in ast.walk(method_node):
        if not isinstance(node, ast.Call):
            continue
        if not isinstance(node.func, ast.Attribute):
            continue
        if not isinstance(node.func.value, ast.Name) or node.func.value.id != "self":
            continue

        helper = node.func.attr
        http_method = REQUEST_HELPERS.get(helper)
        if http_method is None:
            continue

        path = path_from_call(helper, node.args)
        if path is None:
            continue

        endpoints.append((http_method, canonical_path(path), method_node.name))

    return endpoints


def path_from_call(helper, args):
    if helper == "_many":
        if len(args) < 3:
            return None
        return path_from_ast(args[2])

    if helper == "_one":
        if len(args) < 2:
            return None
        return path_from_ast(args[1])

    if helper == "_page":
        if len(args) < 2:
            return None
        return path_from_ast(args[1])

    if not args:
        return None
    return path_from_ast(args[0])


def path_from_ast(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value.startswith("/"):
        return node.value

    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left = path_from_ast(node.left)
        right = path_from_ast(node.right)
        if left is None or right is None:
            return None
        return left + right

    if isinstance(node, ast.Call):
        return path_id_placeholder(node)

    return None


def path_id_placeholder(node):
    if not isinstance(node.func, ast.Attribute):
        return None
    if not isinstance(node.func.value, ast.Name) or node.func.value.id != "self":
        return None
    if node.func.attr != "_path_id" or not node.args:
        return None
    if not isinstance(node.args[0], ast.Name):
        return None

    arg = node.args[0].id
    if arg == "user_id":
        return "{user_id}"
    if arg == "category_id":
        return "{category_id}"
    return "{id}"


def canonical_path(path):
    if not path:
        return path

    path = normalize_path_params(path)

    if path in TOP_TYPE_PATHS:
        return "/me/top/{type}"

    return path


def normalize_path_params(path):
    if "{user_id}" in path or "{category_id}" in path or "{playlist_id}" in path:
        return path

    if path.startswith("/users/") and "{id}" in path:
        return path.replace("{id}", "{user_id}", 1)

    if path.startswith("/browse/categories/") and "{id}" in path:
        return path.replace("{id}", "{category_id}", 1)

    if path.startswith("/playlists/") and "{id}" in path:
        return path.replace("{id}", "{playlist_id}", 1)

    return path


def openapi_endpoints(schema):
    endpoints = []
    for path in sorted(schema.get("paths", {})):
        methods = schema["paths"][path]
        for method in ("DELETE", "GET", "POST", "PUT"):
            operation = methods.get(method.lower())
            if operation is not None:
                endpoints.append((method, path, operation.get("operationId")))
    return tuple(endpoints)


def format_methods(methods):
    if not methods:
        return "(missing)"
    return ", ".join(method + "()" for method in methods)


if __name__ == "__main__":
    main()
