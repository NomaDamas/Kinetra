"""JSON Schema (draft 2020-12, the subset pydantic emits) to TypeScript declarations (C-01d).

Pure functions, no pydantic import. The converter is strict on purpose: a schema keyword it does not know raises
`UnsupportedSchema` with the path to it, so a new model that uses a construct the generator cannot type fails the
export loudly instead of producing a wrong or silently loose TypeScript type.

Mapping:

| JSON Schema | TypeScript |
|---|---|
| `type: string/number/integer/boolean/null` | `string` / `number` / `number` / `boolean` / `null` |
| `const`, `enum` | literal union |
| `anyOf`, `oneOf` | `A \\| B` |
| `$ref: "#/$defs/X"` | `X` |
| `type: array` with `items` | `T[]`; with `prefixItems` and equal `minItems`/`maxItems`: tuple |
| `type: object` with `properties` | `interface` (named, from `$defs`) or inline `{ ... }`; a property absent from `required` is `?:` |
| `type: object` with `additionalProperties: <schema>` only | `Record<string, T>` |

Validation-only keywords (`pattern`, `minimum`, `minLength`, ...) do not change a TypeScript type and are ignored.
"""

from __future__ import annotations

import json
import re
from typing import Any

# Annotations and validation keywords that never change the TypeScript type.
_IGNORED = frozenset(
    {
        "title", "description", "default", "examples", "$comment", "discriminator", "deprecated", "readOnly",
        "writeOnly", "format", "pattern", "minLength", "maxLength", "minimum", "maximum", "exclusiveMinimum",
        "exclusiveMaximum", "multipleOf", "minItems", "maxItems", "uniqueItems", "minProperties", "maxProperties",
    }
)
_PRIMITIVE = {"string": "string", "number": "number", "integer": "number", "boolean": "boolean", "null": "null"}
_IDENT = re.compile(r"^[A-Za-z_$][A-Za-z0-9_$]*$")
_REF = re.compile(r"^#/\$defs/([A-Za-z_][A-Za-z0-9_]*)$")


class UnsupportedSchema(ValueError):
    """The schema uses a construct this converter does not type."""


def _fail(path: str, msg: str) -> UnsupportedSchema:
    return UnsupportedSchema(f"{path or '<root>'}: {msg}")


def _check_keywords(schema: dict[str, Any], handled: set[str], path: str) -> None:
    unknown = sorted(set(schema) - handled - _IGNORED)
    if unknown:
        raise _fail(path, f"unsupported JSON Schema keyword(s) {unknown}; teach packages/core/scripts/schema_to_ts.py")


def _doc(text: str | None, indent: str) -> list[str]:
    if not text:
        return []
    body = text.replace("*/", "*\\/").strip("\n").splitlines()
    if len(body) == 1:
        return [f"{indent}/** {body[0].strip()} */"]
    return [f"{indent}/**", *[f"{indent} * {line.rstrip()}".rstrip() for line in body], f"{indent} */"]


def _key(name: str) -> str:
    return name if _IDENT.match(name) else json.dumps(name, ensure_ascii=False)


def _literal(value: Any, path: str) -> str:
    if value is None or isinstance(value, (bool, int, float, str)):
        return json.dumps(value, ensure_ascii=False)
    raise _fail(path, f"const/enum value {value!r} is not a JSON scalar")


def _union(parts: list[str], atom: bool) -> str:
    seen: list[str] = []
    for p in parts:
        if p not in seen:
            seen.append(p)
    if len(seen) == 1:
        return seen[0]
    joined = " | ".join(seen)
    return f"({joined})" if atom else joined


def type_expr(schema: dict[str, Any], path: str = "", *, atom: bool = False) -> str:
    """TypeScript type expression for `schema`. `atom=True` parenthesises a union (array element position)."""
    if not isinstance(schema, dict):
        raise _fail(path, f"schema must be an object, got {type(schema).__name__}")

    if "$ref" in schema:  # draft 2020-12 allows annotation siblings; anything else beside a $ref is unsupported
        _check_keywords(schema, {"$ref"}, path)
        m = _REF.match(schema["$ref"])
        if not m:
            raise _fail(path, f"only '#/$defs/<Name>' references are supported, got {schema['$ref']!r}")
        return m.group(1)

    if "const" in schema:
        _check_keywords(schema, {"const", "type"}, path)
        return _literal(schema["const"], path)

    if "enum" in schema:
        _check_keywords(schema, {"enum", "type"}, path)
        return _union([_literal(v, path) for v in schema["enum"]], atom)

    for combinator in ("anyOf", "oneOf"):
        if combinator in schema:
            _check_keywords(schema, {combinator}, path)
            members = schema[combinator]
            if not members:
                raise _fail(path, f"empty {combinator}")
            return _union([type_expr(m, f"{path}/{combinator}/{i}", atom=False) for i, m in enumerate(members)], atom)

    kind = schema.get("type")
    if kind is None:
        _check_keywords(schema, set(), path)
        return "unknown"  # {} accepts anything
    if isinstance(kind, list):
        if not kind:
            raise _fail(path, "empty type list")
        _check_keywords(schema, {"type", "items", "properties", "required", "additionalProperties", "prefixItems"}, path)
        return _union([type_expr({**schema, "type": k}, path) for k in kind], atom)
    if kind in _PRIMITIVE:
        _check_keywords(schema, {"type"}, path)
        return _PRIMITIVE[kind]
    if kind == "array":
        return _array(schema, path)
    if kind == "object":
        return _object_inline(schema, path)
    raise _fail(path, f"unsupported type {kind!r}")


def _array(schema: dict[str, Any], path: str) -> str:
    _check_keywords(schema, {"type", "items", "prefixItems"}, path)
    if "prefixItems" in schema:
        if schema.get("minItems") != schema.get("maxItems") or schema.get("minItems") != len(schema["prefixItems"]):
            raise _fail(path, "prefixItems is only supported as a fixed-length tuple (minItems == maxItems == len)")
        if "items" in schema and schema["items"] is not False:
            raise _fail(path, "prefixItems with extra items is not supported")
        return "[" + ", ".join(type_expr(s, f"{path}/prefixItems/{i}") for i, s in enumerate(schema["prefixItems"])) + "]"
    if "items" not in schema:
        return "unknown[]"
    return type_expr(schema["items"], f"{path}/items", atom=True) + "[]"


def _object_parts(schema: dict[str, Any], path: str) -> tuple[dict[str, Any], set[str], Any]:
    _check_keywords(schema, {"type", "properties", "required", "additionalProperties"}, path)
    props = schema.get("properties", {})
    required = set(schema.get("required", []))
    missing = sorted(required - set(props))
    if missing:
        raise _fail(path, f"required names {missing} are not in properties")
    return props, required, schema.get("additionalProperties", True)


def _object_inline(schema: dict[str, Any], path: str) -> str:
    props, required, extra = _object_parts(schema, path)
    if not props:
        if isinstance(extra, dict):
            return f"Record<string, {type_expr(extra, f'{path}/additionalProperties')}>"
        if extra is True:
            return "Record<string, unknown>"
        return "Record<string, never>"
    if isinstance(extra, dict):
        raise _fail(path, "an object with both properties and a typed additionalProperties is not supported")
    fields = [
        f"{_key(n)}{'' if n in required else '?'}: {type_expr(s, f'{path}/properties/{n}')}" for n, s in props.items()
    ]
    return "{ " + "; ".join(fields) + " }"


def _interface(name: str, schema: dict[str, Any], path: str) -> list[str]:
    props, required, extra = _object_parts(schema, path)
    if isinstance(extra, dict):
        raise _fail(path, "an object with both properties and a typed additionalProperties is not supported")
    lines = _doc(schema.get("description"), "")
    lines.append(f"export interface {name} {{")
    for n, s in props.items():
        lines += _doc(s.get("description"), "  ")
        lines.append(f"  {_key(n)}{'' if n in required else '?'}: {type_expr(s, f'{path}/properties/{n}')};")
    lines.append("}")
    return lines


def _is_interface(schema: dict[str, Any]) -> bool:
    return schema.get("type") == "object" and bool(schema.get("properties"))


def render_declarations(defs: dict[str, dict[str, Any]], aliases: dict[str, dict[str, Any]]) -> str:
    """TypeScript source for every named schema: `defs` (models, enums) then `aliases` (exported union types).

    Both are sorted by name so the output does not depend on discovery order.
    """
    clash = sorted(set(defs) & set(aliases))
    if clash:
        raise UnsupportedSchema(f"names exported twice: {clash}")
    blocks: list[str] = []
    for name in sorted(defs):
        schema, path = defs[name], f"#/$defs/{name}"
        if _is_interface(schema):
            blocks.append("\n".join(_interface(name, schema, path)))
        else:
            blocks.append("\n".join([*_doc(schema.get("description"), ""), f"export type {name} = {type_expr(schema, path)};"]))
    for name in sorted(aliases):
        schema = aliases[name]
        blocks.append("\n".join([*_doc(schema.get("description"), ""), f"export type {name} = {type_expr(schema, name)};"]))
    return "\n\n".join(blocks) + "\n"
