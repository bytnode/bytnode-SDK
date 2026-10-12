"""Turn the public OpenAPI contract into a language-neutral description of the SDK.

Everything the two emitters need is computed here, once: the namespace tree
(one node per path segment), the parameters of each route with their Python and
TypeScript types, the row models with stable names, and the pagination flag.
The emitters only format what this module decides.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
SPEC_PATH = ROOT / "spec" / "openapi.json"
OVERRIDES_PATH = Path(__file__).resolve().parent / "overrides.json"

# Envelope keys that are not part of the payload: the SDK exposes them on the
# response object, never inside `data`.
ENVELOPE_KEYS = {"status", "server_time", "data_type", "data", "next", "unavailable", "coverage", "partial"}
# Parameters every list route shares; they get friendlier SDK spellings.
TIME_PARAMS = {"since_ms": "since", "until_ms": "until", "before_ms": "before"}


# --------------------------------------------------------------------------- types


@dataclass
class TypeRef:
    """A field or parameter type, independent of the target language.

    kind: "str" | "int" | "float" | "bool" | "datetime" | "date" | "any"
          | "literal" | "model" | "list" | "dict" | "union"
    """

    kind: str
    nullable: bool = False
    name: str | None = None  # literal alias or model name
    values: tuple[str, ...] = ()  # literal values
    item: TypeRef | None = None  # list item / dict value
    options: tuple[TypeRef, ...] = ()  # union members

    def key(self) -> str:
        """Structural fingerprint, used to deduplicate models."""
        inner = ""
        if self.item:
            inner = self.item.key()
        if self.options:
            inner = "|".join(o.key() for o in self.options)
        return f"{self.kind}:{self.name or ''}:{','.join(self.values)}:{inner}:{int(self.nullable)}"


@dataclass
class Field:
    name: str  # wire name (snake_case, as served by the API)
    type: TypeRef
    description: str = ""
    unit: str = ""
    # The contract declares no `required`: a field is required when every real
    # example of the contract carries it (see `Builder.presence`). A field seen
    # missing once, or never seen, stays optional — the safe side for a client.
    required: bool = False


@dataclass
class Model:
    name: str
    fields: list[Field]
    description: str = ""

    def key(self) -> str:
        return "{" + ";".join(f"{f.name}={f.type.key()}" for f in self.fields) + "}"


@dataclass
class Param:
    wire: str  # name on the wire (`since_ms`, `klines@1h`...)
    name: str  # SDK name, snake_case (`since`, `limit`...)
    type: TypeRef
    location: str  # "query" | "path"
    required: bool
    default: Any = None
    minimum: float | None = None
    maximum: float | None = None
    description: str = ""
    time: bool = False  # accepts a datetime / ISO string / epoch ms


@dataclass
class SnapshotField:
    wire: str  # `klines@1h`, `funding_rate`
    base: str  # `klines`, `funding_rate`
    timeframe: str | None
    route: str | None  # the REST route that serves the same content
    model: str | None
    maximum: int | None
    description: str


@dataclass
class Route:
    path: str
    method: str
    segments: list[str]  # namespace path, SDK spelling (snake_case)
    summary: str
    description: str
    params: list[Param]
    shape: str  # "object" | "list" | "scalar" | "snapshot" | "indicators"
    model: str | None
    paginated: bool
    tag: str
    example: dict[str, Any] | None
    meta: list[str] = field(default_factory=list)  # envelope keys besides the standard ones
    update_frequency_s: int | None = None

    @property
    def ident(self) -> str:
        return "_".join(self.segments)


@dataclass
class Node:
    """One segment of the namespace tree. `route` set = the node is callable."""

    segment: str
    route: Route | None = None
    children: dict[str, Node] = field(default_factory=dict)
    path: tuple[str, ...] = ()


@dataclass
class Literal:
    name: str
    values: tuple[str, ...]
    description: str


@dataclass
class Api:
    version: str
    title: str
    routes: list[Route]
    models: dict[str, Model]
    literals: dict[str, Literal]
    tree: Node
    snapshot_fields: list[SnapshotField]
    indicators: dict[str, Any]
    error_codes: list[str]
    renamed: dict[str, Any]


# --------------------------------------------------------------------------- naming


def snake(text: str) -> str:
    text = text.replace("-", "_").replace(".", "_")
    text = re.sub(r"(?<=[a-z0-9])([A-Z])", r"_\1", text)
    return text.lower()


def pascal(text: str) -> str:
    parts = re.split(r"[_\-\s.@/]+", text)
    return "".join(p[:1].upper() + p[1:] for p in parts if p)


def camel(text: str) -> str:
    p = pascal(text)
    return p[:1].lower() + p[1:]


# --------------------------------------------------------------------------- builder


class Builder:
    def __init__(self, spec: dict[str, Any], overrides: dict[str, Any]) -> None:
        self.spec = spec
        self.ov = overrides
        self.models: dict[str, Model] = {}
        self._by_key: dict[str, str] = {}
        self.literals: dict[str, Literal] = {}
        for lit in overrides["literals"]:
            self.literals[lit["name"]] = Literal(lit["name"], tuple(lit["values"]), lit["description"])

    # ---- schemas -----------------------------------------------------------

    def resolve(self, schema: dict[str, Any]) -> tuple[dict[str, Any], str | None]:
        """Follow a `$ref` to `#/components/schemas/<Name>`; the name becomes the model's."""
        name = None
        while "$ref" in schema:
            ref = schema["$ref"]
            if not ref.startswith("#/components/schemas/"):
                raise ValueError(f"unsupported $ref {ref}")
            name = ref.rsplit("/", 1)[-1]
            schema = {**self.spec["components"]["schemas"][name], **{k: v for k, v in schema.items() if k != "$ref"}}
        return schema, name

    def schema_type(self, schema: dict[str, Any], hint: str) -> TypeRef:
        schema, ref_name = self.resolve(schema)
        if ref_name:
            hint = ref_name
        raw = schema.get("type")
        types = raw if isinstance(raw, list) else [raw] if raw else []
        nullable = "null" in types or bool(schema.get("nullable"))
        types = [t for t in types if t != "null"]
        if "anyOf" in schema or "oneOf" in schema:
            opts = [o for o in schema.get("anyOf", schema.get("oneOf", [])) if o.get("type") != "null"]
            nullable = nullable or len(opts) < len(schema.get("anyOf", schema.get("oneOf", [])))
            if len(opts) == 1:
                t = self.schema_type(opts[0], hint)
                t.nullable = t.nullable or nullable
                return t
            return TypeRef("union", nullable, options=tuple(self.schema_type(o, hint) for o in opts))
        if len(types) > 1:
            return TypeRef("union", nullable, options=tuple(self.schema_type({**schema, "type": t}, hint) for t in types))
        t = types[0] if types else None
        if t == "string":
            fmt = schema.get("format")
            if fmt == "date-time":
                return TypeRef("datetime", nullable)
            if fmt == "date":
                return TypeRef("date", nullable)
            if schema.get("enum"):
                return TypeRef("literal", nullable, values=tuple(schema["enum"]))
            return TypeRef("str", nullable)
        if t == "integer":
            return TypeRef("int", nullable)
        if t == "number":
            return TypeRef("float", nullable)
        if t == "boolean":
            return TypeRef("bool", nullable)
        if t == "array":
            return TypeRef("list", nullable, item=self.schema_type(schema.get("items", {}), hint + "Item"))
        if t == "object":
            props = schema.get("properties")
            if not props:
                return TypeRef("dict", nullable, item=TypeRef("any"))
            return TypeRef("model", nullable, name=self.model(hint, schema, (schema.get("description") or "").strip()))
        return TypeRef("any", True)

    def model(self, name: str, schema: dict[str, Any], description: str = "", fallback: str | None = None) -> str:
        """Register the model of `schema` under `name` and return its final name.

        A model is reused only when the SAME name already holds the SAME
        structure (a latest route and its `/history` serving identical rows).
        Two unrelated routes that happen to share their fields keep their own
        names: a type named after another route would mislead.
        """
        fields = []
        for key, prop in schema.get("properties", {}).items():
            fields.append(
                Field(
                    name=key,
                    type=self.schema_type(prop, name + pascal(key)),
                    description=(prop.get("description") or "").strip(),
                    unit=prop.get("x-unit") or "",
                )
            )
        candidate = Model(name, fields, description)
        key = candidate.key()
        for option in (name, fallback):
            if option and option in self.models and self.models[option].key() == key:
                return option
        for option in (name, fallback):
            if option and option not in self.models:
                candidate.name = option
                self.models[option] = candidate
                return option
        n = 2
        while f"{fallback or name}{n}" in self.models:
            if self.models[f"{fallback or name}{n}"].key() == key:
                return f"{fallback or name}{n}"
            n += 1
        candidate.name = f"{fallback or name}{n}"
        self.models[candidate.name] = candidate
        return candidate.name

    # ---- parameters ----------------------------------------------------------

    def literal_for(self, path: str, prm: dict[str, Any]) -> str | None:
        for rule in self.ov["param_literals"]:
            if rule["param"] != prm["name"]:
                continue
            if "paths" in rule and path not in rule["paths"]:
                continue
            if "description_contains" in rule and rule["description_contains"] not in prm.get("description", ""):
                continue
            if "default" in rule and prm.get("schema", {}).get("default") != rule["default"]:
                continue
            return rule["literal"]
        return None

    def param(self, path: str, prm: dict[str, Any]) -> Param:
        prm, _ = self.resolve(prm)
        wire = prm["name"]
        schema, _ = self.resolve(prm.get("schema", {}))
        lit = self.literal_for(path, prm)
        if lit:
            t = TypeRef("literal", name=lit, values=self.literals[lit].values)
        elif schema.get("enum"):
            # the contract closes the set; a known literal with the same values names it
            values = tuple(schema["enum"])
            name = next((lit.name for lit in self.literals.values() if lit.values == values), None)
            t = TypeRef("literal", name=name, values=values)
        else:
            t = self.schema_type(schema, pascal(wire))
            t.nullable = False
        is_time = wire in TIME_PARAMS
        return Param(
            wire=wire,
            name=TIME_PARAMS.get(wire, snake(wire)),
            type=TypeRef("int") if is_time else t,
            location=prm.get("in", "query"),
            # the contract marks `expiry` optional on max-pain history, its description and the
            # API say it is required (422 `missing_expiry`): the override restores the truth
            required=bool(prm.get("required")) or wire in self.ov.get("force_required", {}).get(path, []),
            default=schema.get("default"),
            minimum=schema.get("minimum"),
            maximum=schema.get("maximum"),
            description=(prm.get("description") or "").strip(),
            time=is_time,
        )

    # ---- routes --------------------------------------------------------------

    def segments(self, path: str) -> list[str]:
        aliases = self.ov["segment_aliases"]
        out = []
        for seg in path.strip("/").split("/")[1:]:  # drop "v1"
            if seg.startswith("{"):
                continue
            out.append(aliases.get(seg, snake(seg)))
        return out

    def model_name(self, path: str) -> str:
        names = self.ov["model_names"]
        if path in names:
            return names[path]
        segs = [s for s in path.strip("/").split("/")[1:] if not s.startswith("{")]
        if segs and segs[-1] == "history":
            base = "/" + "/".join(["v1", *segs[:-1]])
            if base in names:
                return names[base]
            segs = segs[:-1]
        return "".join(pascal(s) for s in segs)

    def route(self, path: str, method: str, op: dict[str, Any]) -> Route:
        resp = op["responses"]["200"]["content"]["application/json"]
        envelope, _ = self.resolve(resp["schema"])
        env = envelope["properties"]
        data_schema = env.get("data", {})
        # A latest-value route types `data` as `anyOf: [<Model>, null]` (the value can be
        # missing, then `unavailable` says why): the model is the non-null member.
        if "anyOf" in data_schema:
            members = [o for o in data_schema["anyOf"] if o.get("type") != "null"]
            if len(members) == 1:
                data_schema = members[0]
        data, ref_name = self.resolve(data_schema)
        if data.get("type") == "array":
            items, item_ref = self.resolve(data.get("items", {}))
            data = {**data, "items": items}
            ref_name = item_ref or ref_name
        params = [self.param(path, p) for p in op.get("parameters", [])]
        shape, model = "object", None
        name = ref_name if ref_name and path not in self.ov["model_names"] else self.model_name(path)
        fallback = name + "History" if path.endswith("/history") and not ref_name else None
        if path == "/v1/snapshot":
            shape = "snapshot"
        elif path == "/v1/indicators":
            shape = "indicators"
        elif data.get("type") == "array":
            shape = "list"
            item = data.get("items", {})
            model = self.model(name, item, fallback=fallback) if item.get("properties") else None
        elif data.get("type") == "object" or "object" in (data.get("type") or []):
            model = self.model(name, data, fallback=fallback) if data.get("properties") else None
        else:
            shape = "scalar"
        return Route(
            path=path,
            method=method.upper(),
            segments=self.segments(path),
            summary=(op.get("summary") or "").strip(),
            description=(op.get("description") or "").strip(),
            params=params,
            shape=shape,
            model=model,
            paginated="next" in env and path not in self.ov["not_paginated"],
            tag=(op.get("tags") or ["Other"])[0],
            example=resp.get("example"),
            meta=[k for k in env if k not in ENVELOPE_KEYS],
            update_frequency_s=op.get("x-update-frequency-seconds"),
        )

    # ---- snapshot ------------------------------------------------------------

    def snapshot_fields(self, routes: dict[str, Route]) -> list[SnapshotField]:
        op = self.spec["paths"]["/v1/snapshot"]["get"]
        out = []
        for prm in op.get("parameters", []):
            prm, _ = self.resolve(prm)
            wire = prm["name"]
            if wire in ("symbol", "fields"):
                continue
            base, _, tf = wire.partition("@")
            desc = prm.get("description", "")
            m = re.search(r"Same content as `(/v1/[^`?]+)", desc)
            route = m.group(1) if m else None
            if route and route not in routes:
                hist = route + "/history"
                route = hist if hist in routes else None
            maximum = None
            for o in prm.get("schema", {}).get("oneOf", []):
                if o.get("type") == "integer":
                    maximum = o.get("maximum")
            out.append(
                SnapshotField(
                    wire=wire,
                    base=base,
                    timeframe=tf or None,
                    route=route,
                    model=routes[route].model if route else None,
                    maximum=maximum,
                    description=desc.strip(),
                )
            )
        return out

    # ---- presence ------------------------------------------------------------

    def presence(self, routes: list[Route], snapshot_fields: list[SnapshotField]) -> None:
        """Mark as required the fields that every real example carries."""
        seen: dict[str, int] = {}
        present: dict[tuple[str, str], int] = {}

        def walk(model_name: str, value: Any) -> None:
            if isinstance(value, list):
                for v in value:
                    walk(model_name, v)
                return
            if not isinstance(value, dict):
                return
            model = self.models[model_name]
            seen[model_name] = seen.get(model_name, 0) + 1
            for f in model.fields:
                if f.name in value:
                    present[(model_name, f.name)] = present.get((model_name, f.name), 0) + 1
                    t = f.type.item if f.type.kind == "list" and f.type.item else f.type
                    if t.kind == "model" and t.name and value[f.name] is not None:
                        walk(t.name, value[f.name])

        for r in routes:
            data = (r.example or {}).get("data")
            if r.model and data is not None:
                walk(r.model, data)
        snap = next((r for r in routes if r.shape == "snapshot"), None)
        if snap and snap.example:
            by_wire = {f.wire: f for f in snapshot_fields}
            for wire, value in (snap.example.get("data") or {}).items():
                f = by_wire.get(wire)
                if f and f.model and value is not None:
                    walk(f.model, value)
        for name, model in self.models.items():
            n = seen.get(name, 0)
            for f in model.fields:
                f.required = n > 0 and present.get((name, f.name), 0) == n

    # ---- tree ----------------------------------------------------------------

    @staticmethod
    def tree(routes: list[Route]) -> Node:
        root = Node("")
        for r in routes:
            node = root
            for i, seg in enumerate(r.segments):
                node = node.children.setdefault(seg, Node(seg, path=tuple(r.segments[: i + 1])))
            if node.route is not None:
                raise ValueError(f"two routes map to the same method: {node.route.path} and {r.path}")
            node.route = r
        return root

    def build(self) -> Api:
        routes = []
        for path, ops in self.spec["paths"].items():
            for method, op in ops.items():
                if method in ("get", "post"):
                    routes.append(self.route(path, method, op))
        by_path = {r.path: r for r in routes}
        snapshot_fields = self.snapshot_fields(by_path)
        self.presence(routes, snapshot_fields)
        err = self.spec["components"]["schemas"]["Error"]["properties"]["error"]["properties"]["code"]
        return Api(
            version=self.spec["info"]["version"],
            title=self.spec["info"]["title"],
            routes=routes,
            models=self.models,
            literals=self.literals,
            tree=self.tree(routes),
            snapshot_fields=snapshot_fields,
            indicators=self.ov["indicators"],
            error_codes=list(err.get("enum", [])),
            renamed=self.spec.get("x-renamed", {}),
        )


def param_literals(api: Api) -> list[str]:
    """Names of the literals used by route parameters (the resource modules import them)."""
    return sorted({p.type.name for r in api.routes for p in r.params if p.type.kind == "literal" and p.type.name})


def load() -> Api:
    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    overrides = json.loads(OVERRIDES_PATH.read_text(encoding="utf-8"))
    return Builder(spec, overrides).build()
