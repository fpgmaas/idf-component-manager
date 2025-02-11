# SPDX-FileCopyrightText: 2022-2023 Espressif Systems (Shanghai) CO LTD
# SPDX-License-Identifier: Apache-2.0
import json
import os
import subprocess
from copy import deepcopy

import jsonschema
import pytest
import vcr
from click.testing import CliRunner
from jsonschema.exceptions import ValidationError

from idf_component_manager.cli.core import initialize_cli
from idf_component_tools.__version__ import __version__
from idf_component_tools.file_cache import FileCache
from idf_component_tools.file_tools import directory_size
from idf_component_tools.manifest import MANIFEST_FILENAME, ManifestManager


@pytest.fixture(autouse=True)
def mock_token(monkeypatch):
    monkeypatch.setenv('IDF_COMPONENT_API_TOKEN', 'test')


def test_raise_exception_on_warnings(monkeypatch):
    # Raises warning in api_client.py in env_cache_time()
    monkeypatch.setenv('IDF_COMPONENT_API_CACHE_EXPIRATION_MINUTES', 'test')

    process = subprocess.Popen(
        ['compote', '--warnings-as-errors', 'project', 'create-from-example', 'example/cmp=3.3.8:cmp'],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE)
    _, stderr = process.communicate()
    decoded = stderr.decode('utf-8')

    assert process.returncode == 1
    assert 'ERROR: IDF_COMPONENT_API_CACHE_EXPIRATION_MINUTES is set to a non-numeric value.' in decoded
    assert 'Please set the variable to the number of minutes. Using the default value of 5 minutes.' in decoded


@vcr.use_cassette('tests/fixtures/vcr_cassettes/test_manifest_create_add_dependency.yaml')
def test_manifest_create_add_dependency(mock_registry):

    runner = CliRunner()
    with runner.isolated_filesystem() as tempdir:

        os.makedirs(os.path.join(tempdir, 'main'))
        os.makedirs(os.path.join(tempdir, 'components', 'foo'))
        os.makedirs(os.path.join(tempdir, 'src'))

        main_manifest_path = os.path.join(tempdir, 'main', MANIFEST_FILENAME)
        foo_manifest_path = os.path.join(tempdir, 'components', 'foo', MANIFEST_FILENAME)
        src_path = os.path.join(tempdir, 'src')
        src_manifest_path = os.path.join(src_path, MANIFEST_FILENAME)

        cli = initialize_cli()
        assert 'Created' in runner.invoke(cli, ['manifest', 'create']).output
        assert 'Created' in runner.invoke(cli, ['manifest', 'create', '--component', 'foo']).output
        assert 'Created' in runner.invoke(cli, ['manifest', 'create', '--path', src_path]).output

        assert runner.invoke(cli, ['manifest', 'create', '--component', 'src', '--path', src_path]).exit_code == 1
        for filepath in [main_manifest_path, foo_manifest_path]:
            with open(filepath, mode='r') as file:
                assert file.readline().startswith('## IDF Component Manager')

        assert 'Successfully added dependency' in runner.invoke(
            cli, ['manifest', 'add-dependency', 'espressif/cmp']).output
        manifest_manager = ManifestManager(main_manifest_path, 'main')
        assert manifest_manager.manifest_tree['dependencies']['espressif/cmp'] == '*'
        assert 'Successfully added dependency' in runner.invoke(
            cli, ['manifest', 'add-dependency', 'espressif/cmp', '--component', 'foo']).output
        manifest_manager = ManifestManager(foo_manifest_path, 'foo')
        assert manifest_manager.manifest_tree['dependencies']['espressif/cmp'] == '*'
        assert 'Successfully added dependency' in runner.invoke(
            cli, ['manifest', 'add-dependency', 'espressif/cmp', '--path', src_path]).output
        manifest_manager = ManifestManager(src_manifest_path, 'src')
        assert manifest_manager.manifest_tree['dependencies']['espressif/cmp'] == '*'


def test_manifest_schema(tmp_path, valid_manifest):
    tempdir = str(tmp_path)

    output = subprocess.check_output(['compote', 'manifest', 'schema'], cwd=tempdir)
    if isinstance(output, bytes):
        output = output.decode('utf8')
    schema_dict = json.loads(output)
    valid_manifest['dependencies']['test']['rules'] = [{'if': 'idf_version < 5'}]
    jsonschema.validate(valid_manifest, schema_dict)

    with pytest.raises(ValidationError, match=r"\[\{'if': 'foo < 5'}]"):
        invalid_manifest = deepcopy(valid_manifest)['dependencies']['test']['rules'] = [{'if': 'foo < 5'}]
        jsonschema.validate(invalid_manifest, schema_dict)

    with pytest.raises(ValidationError, match=r'\[1, 2, 3]'):
        invalid_manifest = deepcopy(valid_manifest)['dependencies']['test']['version'] = [1, 2, 3]
        jsonschema.validate(invalid_manifest, schema_dict)

    with pytest.raises(ValidationError, match=r"'1.2.3.pre.1'"):
        invalid_manifest = deepcopy(valid_manifest)['version'] = '1.2.3.pre.1'
        jsonschema.validate(invalid_manifest, schema_dict)

    with pytest.raises(ValidationError, match=r"'test.me'"):
        invalid_manifest = deepcopy(valid_manifest)['url'] = 'test.me'
        jsonschema.validate(invalid_manifest, schema_dict)


def test_cache_clear(monkeypatch, tmp_path, file_with_size):
    cache_path = tmp_path / 'cache'
    monkeypatch.setenv('IDF_COMPONENT_CACHE_PATH', str(cache_path))

    cache_path.mkdir()
    file_with_size(cache_path / 'file1.txt', 10)

    output = subprocess.check_output(['compote', 'cache', 'clear'])
    assert directory_size(str(cache_path)) == 0
    assert 'Successfully cleared' in output.decode('utf-8')
    assert str(cache_path) in output.decode('utf-8')


def test_cache_path():
    output = subprocess.check_output(['compote', 'cache', 'path'])
    assert FileCache().path() == output.decode('utf-8').strip()


def test_env_cache_path_empty(monkeypatch):
    monkeypatch.setenv('IDF_COMPONENT_CACHE_PATH', '')
    output = subprocess.check_output(['compote', 'cache', 'path'])
    assert FileCache().path() == output.decode('utf-8').strip()


def test_cache_size(monkeypatch, tmp_path, file_with_size):
    monkeypatch.setenv('IDF_COMPONENT_CACHE_PATH', str(tmp_path))

    file_with_size(tmp_path / 'file1.txt', 14)

    output = subprocess.check_output(['compote', 'cache', 'size'])
    assert '14 bytes' == output.decode('utf-8').strip()

    output = subprocess.check_output(['compote', 'cache', 'size', '--bytes'])
    assert '14' == output.decode('utf-8').strip()


def test_version():
    output = subprocess.check_output(['compote', 'version'])
    assert __version__ in output.decode('utf-8')
