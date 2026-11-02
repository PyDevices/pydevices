import argparse
import json
import pprint


DEFAULT_SCHEMA_URL = "https://developer.spotify.com/reference/web-api/open-api-schema.yaml"

CLASS_NAME_OVERRIDES = {
    "AlbumRestrictionObject": "Restriction",
    "ArtistDiscographyAlbumObject": "Album",
    "ChapterRestrictionObject": "Restriction",
    "EpisodeRestrictionObject": "Restriction",
    "TrackRestrictionObject": "Restriction",
    "CurrentlyPlayingContextObject": "CurrentlyPlaying",
    "PlaylistOwnerObject": "User",
    "PlaylistUserObject": "User",
    "PublicUserObject": "User",
    "SimplifiedAlbumObject": "Album",
    "SimplifiedArtistObject": "Artist",
    "SimplifiedAudiobookObject": "Audiobook",
    "SimplifiedChapterObject": "Chapter",
    "SimplifiedEpisodeObject": "Episode",
    "SimplifiedPlaylistObject": "Playlist",
    "SimplifiedShowObject": "Show",
    "SimplifiedTrackObject": "Track",
}

PAGE_CLASS_NAME_OVERRIDES = {
    "CursorPagingObject": "CursorPage",
    "CursorPagingPlayHistoryObject": "PlayHistoryCursorPage",
    "CursorPagingSimplifiedArtistObject": "ArtistCursorPage",
    "PagingArtistObject": "ArtistPage",
    "PagingArtistDiscographyAlbumObject": "AlbumPage",
    "PagingFeaturedPlaylistObject": "FeaturedPlaylists",
    "PagingPlaylistObject": "PlaylistPage",
    "PagingPlaylistTrackObject": "PlaylistTrackPage",
    "PagingSavedAlbumObject": "SavedAlbumPage",
    "PagingSavedEpisodeObject": "SavedEpisodePage",
    "PagingSavedShowObject": "SavedShowPage",
    "PagingSavedTrackObject": "SavedTrackPage",
    "PagingSimplifiedAlbumObject": "AlbumPage",
    "PagingSimplifiedAudiobookObject": "AudiobookPage",
    "PagingSimplifiedChapterObject": "ChapterPage",
    "PagingSimplifiedEpisodeObject": "EpisodePage",
    "PagingSimplifiedShowObject": "ShowPage",
    "PagingSimplifiedTrackObject": "TrackPage",
    "PagingTrackObject": "TrackPage",
}

RESPONSE_NAME_OVERRIDES = {
    "PlaylistSnapshotId": "SnapshotResult",
    "SearchItems": "SearchResults",
}

RESPONSE_PROPERTY_UNWRAPS = {
    "PagedCategories": ("CategoryPage", "categories"),
}

FETCH_METHODS = {
    "Album": "album",
    "Artist": "artist",
    "Audiobook": "audiobook",
    "Chapter": "chapter",
    "Episode": "episode",
    "Playlist": "playlist",
    "Show": "show",
    "Track": "track",
}

PAGING_FIELDS = ("href", "limit", "next", "offset", "previous", "total")

# Hand-curated page-backed properties. The OpenAPI artist/playlist objects do not
# describe these fields; sayso wires them to client page methods instead.
OBJECT_BY_KEY_OVERRIDES = {
    "Artist": (
        {
            "field": "albums",
            "kind": "object_by_key",
            "key": "items",
            "present_class": "AlbumPage",
            "absent_class": "AlbumsRef",
            "page_method": "artist_albums",
        },
    ),
    "Playlist": (
        {
            "field": "items",
            "kind": "object_by_key",
            "key": "items",
            "present_class": "PlaylistTrackPage",
            "absent_class": "PlaylistItemsRef",
            "page_method": "playlist_items",
            "lazy": True,
        },
    ),
}

# Spotify February 2026 Dev Mode removed paths (documented in PORTABILITY.md).
# Do not add fetch_method: "user"; GET /users/{id} is not available in Dev Mode.
FEB_2026_REMOVED_PATHS = (
    "GET /users/{id}",
    "GET /users/{id}/playlists",
    "GET /playlists/{id}/tracks",
    "POST /users/{user_id}/playlists",
    "POST /playlists/{id}/tracks",
    "PUT /playlists/{id}/tracks",
    "DELETE /playlists/{id}/tracks",
    "GET /markets",
)


def main():
    parser = argparse.ArgumentParser(description="Generate draft Spotify object specs from the OpenAPI schema.")
    parser.add_argument("--schema", default=DEFAULT_SCHEMA_URL, help="OpenAPI schema URL or local file path")
    parser.add_argument("--output", default="generated_object_specs.py", help="Output Python file")
    args = parser.parse_args()

    schema = load_schema(args.schema)
    specs = build_specs(schema)
    write_specs(args.output, specs)
    print("wrote:", args.output)
    print("specs:", len(specs))


def load_schema(source):
    text = read_text(source)
    return parse_schema_text(text, source)


def read_text(source):
    if source.startswith("http://") or source.startswith("https://"):
        try:
            from urllib.request import urlopen
        except ImportError:
            raise SystemExit("urllib is required to fetch schema URLs")

        with urlopen(source) as response:
            return response.read().decode("utf-8")

    with open(source, encoding="utf-8") as file:
        return file.read()


def parse_schema_text(text, source="<schema>"):
    stripped = text.lstrip()
    if stripped.startswith("{"):
        return json.loads(text)

    try:
        import yaml
    except ImportError:
        raise SystemExit("Install PyYAML to parse YAML schemas, or pass a JSON OpenAPI schema")

    return yaml.safe_load(text)


def build_specs(schema):
    components = schema.get("components", {})
    schemas = components.get("schemas", {})
    responses = components.get("responses", {})
    specs_by_name = {}

    for schema_name in sorted(schemas):
        item = resolve_schema(schemas[schema_name], schemas)
        properties = item.get("properties")
        if not properties:
            continue

        class_name = schema_to_class_name(schema_name)
        add_spec(specs_by_name, class_name, properties)

    for response_name in sorted(responses):
        response = responses[response_name]
        item = response_body_schema(response)
        if item is None:
            continue

        if response_name in RESPONSE_PROPERTY_UNWRAPS:
            class_name, property_name = RESPONSE_PROPERTY_UNWRAPS[response_name]
            properties = item.get("properties", {})
            item = properties.get(property_name)
            if item is None:
                continue
            item = resolve_schema(item, schemas)
        elif response_name in RESPONSE_NAME_OVERRIDES:
            class_name = RESPONSE_NAME_OVERRIDES[response_name]
            item = resolve_schema(item, schemas)
        else:
            continue

        properties = item.get("properties")
        if properties:
            add_spec(specs_by_name, class_name, properties)

    specs = []
    for name in sorted(specs_by_name):
        spec = specs_by_name[name]
        specs.append(apply_property_overrides(finalize_spec(spec)))

    return tuple(specs)


def apply_property_overrides(spec):
    overrides = OBJECT_BY_KEY_OVERRIDES.get(spec.get("name"))
    if overrides is None:
        return spec

    properties = {}
    for prop in spec.get("properties", ()):
        properties[prop["field"]] = prop
    for prop in overrides:
        properties[prop["field"]] = prop

    updated = dict(spec)
    updated["properties"] = tuple(properties[field] for field in sorted(properties))
    return updated


def finalize_spec(spec):
    properties = spec["properties"]

    if spec["name"] == "Paging":
        return with_fetch_method({
            "name": "Paging",
            "base": "Page",
        })

    if spec["name"] == "CursorPaging":
        return with_fetch_method({
            "name": "CursorPaging",
            "base": "Page",
            "properties": (
                {"field": "cursors", "kind": "object", "class": "Cursor"},
            ),
        })

    item = properties.get("items")
    if item is not None and item.get("kind") == "objects" and has_paging_fields(properties):
        base = "CursorPaging" if "cursors" in properties else "Paging"
        page_spec = {
            "name": spec["name"],
            "base": base,
            "item_class": item["class"],
        }
        extra_properties = tuple(
            properties[field]
            for field in sorted(properties)
            if field != "items"
            and field not in PAGING_FIELDS
            and not (base == "CursorPaging" and field == "cursors")
        )
        if extra_properties:
            page_spec["properties"] = extra_properties
        return with_fetch_method(page_spec)

    if has_paging_fields(properties) and "cursors" in properties:
        return with_fetch_method({
            "name": spec["name"],
            "base": "CursorPaging",
        })

    return with_fetch_method({
        "name": spec["name"],
        "properties": tuple(properties[field] for field in sorted(properties)),
    })


def with_fetch_method(spec):
    fetch_method = FETCH_METHODS.get(spec["name"])
    if fetch_method is not None:
        spec["fetch_method"] = fetch_method
    return spec


def has_paging_fields(properties):
    return "href" in properties and "limit" in properties and "next" in properties


def add_spec(specs_by_name, class_name, properties):
    spec = specs_by_name.get(class_name)
    if spec is None:
        spec = {
            "name": class_name,
            "properties": {},
        }
        specs_by_name[class_name] = spec

    for name in sorted(properties):
        spec["properties"][name] = property_spec(name, properties[name])


def response_body_schema(response):
    content = response.get("content", {})
    media_type = content.get("application/json")
    if media_type is None:
        return None
    return media_type.get("schema")


def resolve_schema(schema, schemas):
    if "$ref" in schema:
        return resolve_schema(schemas[ref_name(schema["$ref"])], schemas)

    if "allOf" in schema:
        merged = {"properties": {}}
        for item in schema["allOf"]:
            resolved = resolve_schema(item, schemas)
            merged["properties"].update(resolved.get("properties", {}))
        return merged

    return schema


def property_spec(field, schema):
    ref = schema_ref_name(schema)
    if ref is not None:
        return {
            "field": field,
            "kind": "object",
            "class": schema_to_class_name(ref),
        }

    type_map = schema_type_map(schema)
    if type_map is not None:
        return {
            "field": field,
            "kind": "typed_object",
            "type_map": type_map,
        }

    if schema.get("type") == "array":
        items = schema.get("items", {})
        ref = schema_ref_name(items)
        if ref is not None:
            return {
                "field": field,
                "kind": "objects",
                "class": schema_to_class_name(ref),
            }
        type_map = schema_type_map(items)
        if type_map is not None:
            return {
                "field": field,
                "kind": "typed_objects",
                "type_map": type_map,
            }
        return {
            "field": field,
            "kind": "tuple",
        }

    return {
        "field": field,
    }


def schema_ref_name(schema):
    if "$ref" in schema:
        return ref_name(schema["$ref"])

    for item in schema.get("allOf", ()):
        if "$ref" in item:
            return ref_name(item["$ref"])

    return None


def schema_type_map(schema):
    refs = []
    for union_key in ("oneOf", "anyOf"):
        for item in schema.get(union_key, ()):
            ref = schema_ref_name(item)
            if ref is not None:
                refs.append(ref)

    if not refs:
        return None

    type_map = {}
    for ref in sorted(refs):
        class_name = schema_to_class_name(ref)
        type_map[class_name[:1].lower() + class_name[1:]] = class_name
    return type_map


def ref_name(ref):
    return ref.rsplit("/", 1)[-1]


def schema_to_class_name(schema_name):
    if schema_name in CLASS_NAME_OVERRIDES:
        return CLASS_NAME_OVERRIDES[schema_name]
    if schema_name in PAGE_CLASS_NAME_OVERRIDES:
        return PAGE_CLASS_NAME_OVERRIDES[schema_name]

    name = schema_name
    for suffix in ("Object", "Base"):
        if name.endswith(suffix):
            name = name[: -len(suffix)]
    return "".join(part for part in name.replace("-", "_").split("_") if part)


def write_specs(path, specs):
    with open(path, "w", encoding="utf-8") as file:
        file.write("# Generated draft. Review before copying into sayso.object_specs.\n")
        file.write("#\n")
        file.write("# Hydration: do not emit per-field fetch flags. Types in FETCH_METHODS\n")
        file.write("# hydrate missing fields via SpotifyObject._get(); page-backed fields\n")
        file.write("# use object_by_key + page_method (see OBJECT_BY_KEY_OVERRIDES).\n")
        file.write("# Cursor paging types use base CursorPaging (extends Page + cursors).\n")
        file.write("#\n")
        file.write("# February 2026 Dev Mode removed paths (see PORTABILITY.md):\n")
        for removed_path in FEB_2026_REMOVED_PATHS:
            file.write("#   - {}\n".format(removed_path))
        file.write("SPOTIFY_OBJECT_SPECS = ")
        file.write(pprint.pformat(specs, width=120))
        file.write("\n")


if __name__ == "__main__":
    main()
