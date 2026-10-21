from .object_specs import SPOTIFY_OBJECT_SPECS
from .transport import TransportError


_MISSING = object()
_current_client = None
_CLASS_REGISTRY = {}
_PAGE_FIELDS = ("href", "limit", "next", "offset", "previous", "total")


class HydrationError(Exception):
    def __init__(self, message, cause=None):
        self.args = (message,)
        self.cause = cause


def set_client(client):
    global _current_client
    _current_client = client


def get_client():
    return _current_client


def _hydration_error(obj, error, page_method=None):
    endpoint = page_method or obj.__class__._fetch_method
    name = obj.__class__.__name__
    object_id = obj._peek("id")

    message = "Failed to hydrate {}".format(name)
    if object_id is not None:
        message += " (id={!r})".format(object_id)
    if endpoint is not None:
        message += " via {}()".format(endpoint)
    if error.status is not None:
        message += ": HTTP {}".format(error.status)

    if endpoint == "user":
        message += (
            ". GET /users/{id} is unavailable in Spotify Dev Mode;"
            " use client.me() for the current user."
        )
    elif error.status == 403:
        message += (
            " This may be a followed playlist, collaborator restriction,"
            " or a February 2026 Dev Mode removed endpoint."
        )

    return HydrationError(message, error)


class SpotifyObject:
    _fetch_method = None

    def __init__(self, data=None, **kwargs):
        if data is None:
            data = kwargs
        elif kwargs:
            data.update(kwargs)

        self._data = data or {}
        self._fetched = False

    def _peek(self, field):
        value = self._data.get(field, _MISSING)
        if value is _MISSING:
            return None
        return value

    def _can_hydrate(self):
        return self.__class__._fetch_method is not None

    def _get(self, field):
        value = self._data.get(field, _MISSING)

        if value is _MISSING and not self._fetched:
            self._fetch()
            value = self._data.get(field, _MISSING)

        if value is _MISSING:
            return None

        return value

    def _get_embedded_field(self, field, key):
        data = self._get(field)

        if (
            not self._fetched
            and self._can_hydrate()
            and (data is None or key not in data)
        ):
            self._fetch()
            data = self._peek(field)

        return data

    def raw(self):
        return self._data

    def _fetch(self):
        if self._fetched or not self._can_hydrate():
            return self

        client = get_client()
        if client is None:
            return self

        object_id = self._peek("id")
        if object_id is None:
            return self

        try:
            fresh = self._fetch_object(client, object_id)
        except TransportError as error:
            raise _hydration_error(self, error)

        if fresh is not None:
            self._data.update(fresh.raw())
            self._fetched = True

        return self

    def _fetch_object(self, client, object_id):
        return None

    def _object(self, cls, field):
        data = self._get(field)
        if data is None:
            return None
        return cls(data)

    def _objects(self, cls, field):
        data = self._get(field)
        if data is None:
            return ()
        return [cls(item) for item in data]

    def _typed_object(self, field, type_map):
        data = self._get(field)
        if data is None:
            return None
        return _resolve_typed_item(data, type_map)

    def _typed_objects(self, field, type_map):
        data = self._get(field)
        if data is None:
            return ()
        return [_resolve_typed_item(item, type_map) for item in data]

    def __repr__(self):
        cls = self.__class__.__name__
        name = self._peek("name")
        object_id = self._peek("id")

        if name is not None and object_id is not None:
            return "<{} name={!r} id={!r}>".format(cls, name, object_id)
        if object_id is not None:
            return "<{} id={!r}>".format(cls, object_id)
        return "<{}>".format(cls)

    def __str__(self):
        try:
            import json
        except ImportError:
            return repr(self._data)

        try:
            return json.dumps(self._data, indent=2, sort_keys=True)
        except TypeError:
            return repr(self._data)


class Page(SpotifyObject):
    _item_class = None

    @property
    def items(self):
        data = self._peek("items")
        if data is None:
            return ()

        cls = _resolve_class(self._item_class)
        if cls is None:
            return data

        return [cls(item) for item in data]

    def __iter__(self):
        return iter(self.items)

    def __len__(self):
        return len(self.items)

    def __getitem__(self, index):
        return self.items[index]


class LazyPageRef(SpotifyObject):
    def __init__(self, owner, page_method, present_cls_name, ref_data=None):
        super().__init__(ref_data or {})
        self._owner = owner
        self._page_method = page_method
        self._present_cls_name = present_cls_name
        self._page = None

    def _load_page(self):
        if self._page is not None:
            return self._page

        client = get_client()
        object_id = self._owner._peek("id")
        if client is None or object_id is None:
            raise HydrationError(
                "Cannot load {} without a client and owner id".format(self._page_method)
            )

        try:
            page = getattr(client, self._page_method)(object_id)
        except TransportError as error:
            raise _hydration_error(self._owner, error, self._page_method)

        self._page = page
        return self._page

    def __iter__(self):
        return iter(self._load_page())

    def __len__(self):
        return len(self._load_page())

    def __getitem__(self, index):
        return self._load_page()[index]


def _resolve_class(name):
    if name is None:
        return None
    return _CLASS_REGISTRY[name]


def _resolve_typed_item(item, type_map):
    cls_name = type_map.get(item.get("type"))
    if cls_name is None:
        return SpotifyObject(item)
    return _resolve_class(cls_name)(item)


def _field_property(field, empty=None):
    def getter(self):
        value = self._get(field)
        if value is None and empty is not None:
            return empty
        return value

    return property(getter)


def _object_property(cls_name, field):
    def getter(self):
        return self._object(_resolve_class(cls_name), field)

    return property(getter)


def _objects_property(cls_name, field):
    def getter(self):
        return self._objects(_resolve_class(cls_name), field)

    return property(getter)


def _object_by_key_property(
    field,
    key,
    present_cls_name,
    absent_cls_name,
    page_method=None,
    lazy=False,
):
    def getter(self):
        if lazy and page_method is not None:
            data = self._peek(field)
            if data is None and not self._fetched and self._can_hydrate():
                self._fetch()
                data = self._peek(field)

            if data is not None and key in data:
                return _resolve_class(present_cls_name)(data)

            return LazyPageRef(self, page_method, present_cls_name, data)

        data = self._get_embedded_field(field, key)

        if data is not None and key in data:
            return _resolve_class(present_cls_name)(data)

        if page_method is not None:
            client = get_client()
            object_id = self._peek("id")
            if client is not None and object_id is not None:
                try:
                    return getattr(client, page_method)(object_id)
                except TransportError as error:
                    raise _hydration_error(self, error, page_method)

        if data is None:
            return None

        return _resolve_class(absent_cls_name)(data)

    return property(getter)


def _typed_object_property(field, type_map):
    def getter(self):
        return self._typed_object(field, type_map)

    return property(getter)


def _typed_objects_property(field, type_map):
    def getter(self):
        return self._typed_objects(field, type_map)

    return property(getter)


def _property_for_spec(prop):
    field = prop["field"]
    kind = prop.get("kind", "field")

    if kind == "field":
        return _field_property(field)
    if kind == "tuple":
        return _field_property(field, empty=())
    if kind == "object":
        return _object_property(prop["class"], field)
    if kind == "objects":
        return _objects_property(prop["class"], field)
    if kind == "object_by_key":
        return _object_by_key_property(
            field,
            prop["key"],
            prop["present_class"],
            prop["absent_class"],
            prop.get("page_method"),
            prop.get("lazy", False),
        )
    if kind == "typed_object":
        return _typed_object_property(field, prop["type_map"])
    if kind == "typed_objects":
        return _typed_objects_property(field, prop["type_map"])

    raise ValueError("unknown property kind: {!r}".format(kind))


def make_spotify_class(spec):
    name = spec["name"]
    attrs = {}

    base = spec.get("base")
    if base is not None:
        base_class = _resolve_class(base)
        attrs["_item_class"] = spec.get("item_class")
    else:
        base_class = SpotifyObject

    for prop in spec.get("properties", ()):
        attrs[prop["field"]] = _property_for_spec(prop)

    fetch_method = spec.get("fetch_method")
    if fetch_method is not None:
        attrs["_fetch_method"] = fetch_method

        def _fetch_object(self, client, object_id):
            return getattr(client, fetch_method)(object_id)

        attrs["_fetch_object"] = _fetch_object

    return type(name, (base_class,), attrs)


def make_spotify_classes(specs):
    classes = {}
    _CLASS_REGISTRY["Page"] = Page
    _CLASS_REGISTRY["LazyPageRef"] = LazyPageRef
    globals()["Page"] = Page
    globals()["LazyPageRef"] = LazyPageRef

    for spec in specs:
        cls = make_spotify_class(spec)
        classes[spec["name"]] = cls
        _CLASS_REGISTRY[spec["name"]] = cls
        globals()[spec["name"]] = cls
    return classes


for _page_field in _PAGE_FIELDS:
    setattr(Page, _page_field, _field_property(_page_field))

for _lazy_ref_field in ("href", "total"):
    setattr(LazyPageRef, _lazy_ref_field, _field_property(_lazy_ref_field))


make_spotify_classes(SPOTIFY_OBJECT_SPECS)
