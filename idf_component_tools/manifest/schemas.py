# SPDX-FileCopyrightText: 2023 Espressif Systems (Shanghai) CO LTD
# SPDX-License-Identifier: Apache-2.0

import re

from schema import And, Optional, Or, Regex, Schema, Use
from six import reraise, string_types

from idf_component_manager.utils import RE_PATTERN

from ..constants import COMPILED_GIT_URL_RE, COMPILED_URL_RE
from ..errors import InternalError
from ..semver import SimpleSpec, Version
from .constants import (
    FULL_SLUG_REGEX, KNOWN_BUILD_METADATA_FIELDS, KNOWN_INFO_METADATA_FIELDS, TAGS_REGEX, known_targets)
from .if_parser import IfClause, parse_if_clause

try:
    from typing import Any
except ImportError:
    pass

KNOWN_FILES_KEYS = [
    'include',
    'exclude',
]
KNOWN_EXAMPLES_KEYS = ['path']
KNOWN_IF_CLAUSE_KEYWORDS = ['IDF_TARGET', 'IDF_VERSION']

NONEMPTY_STRING = And(Or(*string_types), len, error='Non-empty string is required here')

LINKS_URL_ERROR = 'Invalid URL in the "{}" field. Check that link is a correct HTTP(S) URL. '
LINKS_GIT_ERROR = 'Invalid URL in the "{}" field. Check that link is a valid Git remote URL'


def _dependency_schema():  # type: () -> Or
    return Or(
        Or(None, *string_types, error='Dependency version spec format is invalid'),
        {
            Optional('version'): Or(None, *string_types, error='Dependency version spec format is invalid'),
            Optional('public'): Use(bool, error='Invalid format of dependency public flag'),
            Optional('path'): NONEMPTY_STRING,
            Optional('git'): NONEMPTY_STRING,
            Optional('service_url'): NONEMPTY_STRING,
            Optional('rules'): [{
                'if': Use(parse_if_clause)
            }],
            Optional('override_path'): NONEMPTY_STRING,
            Optional('require'): Or(
                'public',
                'private',
                'no',
                False,
                error='Invalid format of dependency require field format. '
                'Should be "public", "private" or "no"',
            ),
            Optional('pre_release'): Use(bool, error='Invalid format of dependency pre_release flag'),
        },
        error='Invalid dependency format',
    )


DEPENDENCY_SCHEMA = _dependency_schema()


def _manifest_schema():  # type: () -> Schema
    return Schema(
        {
            Optional('name'): Or(*string_types),
            Optional('version'): Or(Version.parse, error='Component version should be valid semantic version'),
            Optional('targets'): known_targets(),
            Optional('maintainers'): [NONEMPTY_STRING],
            Optional('description'): NONEMPTY_STRING,
            Optional('tags'): [
                Regex(
                    TAGS_REGEX,
                    error='Invalid tag. Tags may be between 3 and 32 symbols long and may contain '
                    'letters, numbers, _ and -',
                )
            ],
            Optional('dependencies'): {
                Optional(Regex(FULL_SLUG_REGEX, error='Invalid dependency name')): DEPENDENCY_SCHEMA,
            },
            Optional('files'): {Optional(key): [NONEMPTY_STRING]
                                for key in KNOWN_FILES_KEYS},
            Optional('examples'): [{key: NONEMPTY_STRING
                                    for key in KNOWN_EXAMPLES_KEYS}],
            # Links of the project
            Optional('url'): Regex(COMPILED_URL_RE, error=LINKS_URL_ERROR.format('url')),
            Optional('repository'): Regex(COMPILED_GIT_URL_RE, error=LINKS_GIT_ERROR.format('repository')),
            Optional('documentation'): Regex(COMPILED_URL_RE, error=LINKS_URL_ERROR.format('documentation')),
            Optional('issues'): Regex(COMPILED_URL_RE, error=LINKS_URL_ERROR.format('issues')),
            Optional('discussion'): Regex(COMPILED_URL_RE, error=LINKS_URL_ERROR.format('discussion')),
        },
        error='Invalid manifest format',
    )


MANIFEST_SCHEMA = _manifest_schema()


def version_json_schema():  # type: () -> dict
    return {'type': 'string', 'pattern': SimpleSpec.regex_str()}


def manifest_json_schema():  # type: () -> dict
    def replace_regex_pattern_with_pattern_str(pat):  # type: (re.Pattern) -> Any
        return pat.pattern

    def process_json_schema(
            obj,  # type: dict[str, Any] | list | str | Any
    ):  # type: (...) -> dict[str, Any] | list | str | Any
        if isinstance(obj, dict):
            # jsonschema 2.5.1 for python 3.4 does not support empty `required` field
            if not obj.get('required', []):
                obj.pop('required', None)

            return {k: process_json_schema(v) for k, v in obj.items()}
        elif isinstance(obj, RE_PATTERN):
            # `re.Pattern` should use the pattern string instead
            return replace_regex_pattern_with_pattern_str(obj)
        elif isinstance(obj, (list, tuple)):
            # yaml dict won't have other iterable data types
            return [process_json_schema(i) for i in obj]

        # we don't process other data types, like numbers
        return obj

    json_schema = MANIFEST_SCHEMA.json_schema(
        'idf-component-manager')  # here id should be an url to use $ref in the future

    # Polish starts here

    # The "schema" library we're currently using does not support auto-generate JSON Schema for nested schema.
    # We need to add it back by ourselves
    #
    # `version`
    json_schema['properties']['version'] = version_json_schema()
    # `dependency`
    json_schema['properties']['dependencies']['additionalProperties'] = {
        'anyOf': Schema(DEPENDENCY_SCHEMA).json_schema('#dependency')['anyOf']
    }
    # `dependencies:*:version` could be simple spec version, or git branch/commit, use string instead
    _anyof = json_schema['properties']['dependencies']['additionalProperties']['anyOf']
    _anyof[0] = {'type': 'string'}
    _anyof[1]['properties']['version'] = {'type': 'string'}
    # `if` clause
    _anyof[1]['properties']['rules']['items']['properties']['if'] = {'type': 'string', 'pattern': IfClause.regex_str()}

    # The "schema" library is also missing the `type` for the following types
    # - enum - it's optional in JSON schema, but it's important to the error messages
    # - boolean - it's mandatory, otherwise the schema could also accept random strings
    json_schema['properties']['targets']['items']['type'] = 'string'
    _anyof[1]['properties']['pre_release']['type'] = 'boolean'
    _anyof[1]['properties']['public']['type'] = 'boolean'
    _anyof[1]['properties']['require']['type'] = 'string'

    # normalize the final json schema
    json_schema = process_json_schema(json_schema)

    return json_schema


JSON_SCHEMA = manifest_json_schema()


def _flatten_json_schema_keys(schema, stack=None):
    def subschema_key(_schema):
        for sub_k in _schema:
            if sub_k in ['allOf', 'anyOf', 'oneOf', 'not']:
                return sub_k

        return None

    if stack is None:
        stack = []

    subkey = subschema_key(schema)
    if subkey:
        res = []
        for s in schema[subkey]:
            res += _flatten_json_schema_keys(s, stack)
        return res
    elif schema['type'] == 'object':
        res = []
        if 'properties' in schema and schema['properties']:
            for k, v in schema['properties'].items():
                # v is a dictionary
                cur = stack + [k]

                if v['type'] == 'object':
                    res.extend(_flatten_json_schema_keys(v, cur))
                elif v['type'] == 'array':
                    res.extend(_flatten_json_schema_keys(v['items'], cur + ['type:array']))
                else:
                    res.append(cur + ['type:' + v['type']])

        if 'additionalProperties' in schema and schema['additionalProperties']:
            res.extend(_flatten_json_schema_keys(schema['additionalProperties'], stack + ['*']))

        return res
    else:
        return [stack + ['type:' + schema['type']]]


def serialize_list_of_list_of_strings(ll_str):
    """
    flatten list of strings to '-' joined values.

    This would make database storage much easier.
    """
    res = []
    for key in ll_str:
        new_str = '-'.join(key)
        if new_str not in res:
            res.append(new_str)

    return sorted(res)


_build_metadata_keys = []  # type: list[str]
_info_metadata_keys = []  # type: list[str]
for _key in sorted(_flatten_json_schema_keys(JSON_SCHEMA)):
    if _key[0] in KNOWN_BUILD_METADATA_FIELDS:
        _build_metadata_keys.append(_key)
    elif _key[0] in KNOWN_INFO_METADATA_FIELDS:
        _info_metadata_keys.append(_key)
    else:
        reraise(InternalError, ValueError('Unknown JSON Schema key {}'.format(_key[0])))

BUILD_METADATA_KEYS = serialize_list_of_list_of_strings(_build_metadata_keys)
INFO_METADATA_KEYS = serialize_list_of_list_of_strings(_info_metadata_keys)

METADATA_SCHEMA = Schema({
    Optional('build_keys'): BUILD_METADATA_KEYS,
    Optional('info_keys'): INFO_METADATA_KEYS,
})
