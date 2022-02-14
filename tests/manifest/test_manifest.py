import os
import re
import shutil
import tempfile

import pytest

from idf_component_manager.dependencies import detect_unused_components
from idf_component_tools.errors import ManifestError
from idf_component_tools.hash_tools import HASH_FILENAME
from idf_component_tools.manifest import (
    SLUG_REGEX, ComponentVersion, ManifestManager, ManifestValidator, SolvedComponent)
from idf_component_tools.manifest.validator import DEFAULT_KNOWN_TARGETS, known_targets


class TestComponentVersion(object):
    def test_comparison(self):
        versions = [
            ComponentVersion('3.0.4'),
            ComponentVersion('3.0.6'),
            ComponentVersion('3.0.5'),
        ]

        assert versions[0] == ComponentVersion('3.0.4')
        assert versions[0] != ComponentVersion('*')
        assert versions[0] != ComponentVersion('699d3202533d13b55df3021d93352d8c242ee81e')
        assert str(max(versions)) == '3.0.6'

    def test_flags(self):
        semver = ComponentVersion('1.2.3')
        assert semver.is_semver
        assert not semver.is_commit_id
        assert not semver.is_any

        semver = ComponentVersion('*')
        assert not semver.is_semver
        assert not semver.is_commit_id
        assert semver.is_any

        semver = ComponentVersion('699d3202533d13b55df3021d93352d8c242ee81e')
        assert not semver.is_semver
        assert semver.is_commit_id
        assert not semver.is_any


class TestManifestPipeline(object):
    def test_check_filename(self, tmp_path):
        path = tmp_path.as_posix()
        parser = ManifestManager(path, name='test')

        parser.check_filename()

        assert parser._path == os.path.join(path, 'idf_component.yml')

    def test_parse_invalid_yaml(self):
        manifest_path = os.path.join(os.path.dirname(os.path.realpath(__file__)), '..', 'fixtures', 'invalid_yaml.yml')
        parser = ManifestManager(manifest_path, name='fixtures')

        with pytest.raises(ManifestError) as e:
            parser.manifest_tree

        assert e.type == ManifestError
        assert str(e.value).startswith('Cannot parse')

    def test_parse_valid_yaml(self, capsys):
        manifest_path = os.path.join(os.path.dirname(os.path.realpath(__file__)), '..', 'fixtures', 'idf_component.yml')
        parser = ManifestManager(manifest_path, name='fixtures')

        assert len(parser.manifest_tree.keys()) == 7

    def test_prepare(self):
        manifest_path = os.path.join(os.path.dirname(os.path.realpath(__file__)), '..', 'fixtures', 'idf_component.yml')
        parser = ManifestManager(manifest_path, name='fixtures')

        parser.load()

        assert parser.is_valid


class TestManifestValidator(object):
    def test_validate_unknown_root_key(self, valid_manifest):
        valid_manifest['unknown'] = 'test'
        valid_manifest['test'] = 'test'
        validator = ManifestValidator(valid_manifest)

        errors = validator.validate_normalize()

        assert len(errors) == 2
        assert errors[1].startswith('Unknown keys: test, unknown')

    def test_validate_unknown_root_values(self, valid_manifest):
        valid_manifest['version'] = '1!.3.3'
        validator = ManifestValidator(valid_manifest)

        errors = validator.validate_normalize()

        assert len(errors) == 2
        assert errors[1].startswith('Component version should be valid')

    def test_validate_component_versions_not_in_manifest(self, valid_manifest):
        valid_manifest.pop('dependencies')
        validator = ManifestValidator(valid_manifest)

        errors = validator.validate_normalize()

        assert not errors

    def test_validate_component_version_normalization(self, valid_manifest):
        valid_manifest['dependencies'] = {'test': '1.2.3', 'pest': {'version': '3.2.1'}}
        validator = ManifestValidator(valid_manifest)

        errors = validator.validate_normalize()

        assert not errors
        assert validator.manifest_tree['dependencies'] == {
            'test': {
                'version': '1.2.3'
            },
            'pest': {
                'version': '3.2.1'
            },
        }

    def test_validate_component_versions_are_empty(self, valid_manifest):
        valid_manifest['dependencies'] = {}
        validator = ManifestValidator(valid_manifest)

        errors = validator.validate_normalize()

        assert not errors

    def test_validate_component_versions_not_a_dict(self, valid_manifest):
        valid_manifest['dependencies'] = ['one_component', 'another-one']
        validator = ManifestValidator(valid_manifest)

        errors = validator.validate_normalize()

        assert len(errors) == 2
        assert errors[1].startswith('List of dependencies should be a dictionary')

    def test_validate_component_versions_unknown_key(self, valid_manifest):
        valid_manifest['dependencies'] = {'test-component': {'version': '^1.2.3', 'persion': 'asdf'}}
        validator = ManifestValidator(valid_manifest)

        errors = validator.validate_normalize()

        assert len(errors) == 4
        assert errors[3] == 'Unknown keys in dependency details: persion'

    def test_validate_component_versions_invalid_name(self, valid_manifest):
        valid_manifest['dependencies'] = {'asdf!fdsa': {'version': '^1.2.3'}}
        validator = ManifestValidator(valid_manifest)

        errors = validator.validate_normalize()

        assert len(errors) == 2
        assert errors[1].startswith('Component\'s name is not valid "asdf!fdsa",')

    def test_validate_component_versions_invalid_spec_subkey(self, valid_manifest):
        valid_manifest['dependencies'] = {'test-component': {'version': '^1.2a.3'}}
        validator = ManifestValidator(valid_manifest)

        errors = validator.validate_normalize()

        assert len(errors) == 1
        assert errors[0].startswith('Version specifications for "test-component" are invalid.')

    def test_validate_component_versions_invalid_spec(self, valid_manifest):
        valid_manifest['dependencies'] = {'test-component': '~=1a.2.3'}
        validator = ManifestValidator(valid_manifest)

        errors = validator.validate_normalize()

        assert len(errors) == 1
        assert errors[0].startswith('Version specifications for "test-component" are invalid.')

    def test_validate_targets_unknown(self, valid_manifest):
        valid_manifest['targets'] = ['esp123', 'esp32', 'asdf']
        validator = ManifestValidator(valid_manifest)

        errors = validator.validate_normalize()

        assert len(errors) == 2
        assert errors[1].startswith('Unknown targets: esp123, asdf')

    def test_slug_re(self):
        valid_names = ('asdf-fadsf', '123', 'asdf_erw', 'as_df_erw', 'test-stse-sdf_sfd')
        invalid_names = ('!', 'asdf$f', 'daf411~', 'adf\nadsf', '_', '-', '_good', 'asdf-_-fdsa-')

        for name in valid_names:
            assert re.match(SLUG_REGEX, name)

        for name in invalid_names:
            assert not re.match(SLUG_REGEX, name)

    def test_validate_version_list(self, valid_manifest):
        validator = ManifestValidator(valid_manifest)

        errors = validator.validate_normalize()

        assert not errors

    def test_check_required_keys(self, valid_manifest):
        validator = ManifestValidator(valid_manifest, check_required_fields=True)

        errors = validator.validate_normalize()

        assert not errors

    def test_check_required_keys_empty_manifest(self):
        validator = ManifestValidator({}, check_required_fields=True)

        errors = validator.validate_normalize()

        assert len(errors) == 1

    def test_validate_files_invalid_format(self, valid_manifest):
        valid_manifest['files']['include'] = 34
        validator = ManifestValidator(valid_manifest)
        errors = validator.validate_normalize()

        assert len(errors) == 1

    def test_validate_files_invalid_path(self, valid_manifest):
        valid_manifest['files']['include'] = 34
        validator = ManifestValidator(valid_manifest)
        errors = validator.validate_normalize()

        assert len(errors) == 1

    def test_validate_tags_invalid_length(self, valid_manifest):
        valid_manifest['tags'].append('sm')
        validator = ManifestValidator(valid_manifest)
        errors = validator.validate_normalize()

        assert len(errors) == 2
        assert errors[1].startswith('Invalid tag')

    def test_validate_tags_invalid_symbols(self, valid_manifest):
        valid_manifest['tags'].append('wrOng t@g')
        validator = ManifestValidator(valid_manifest)
        errors = validator.validate_normalize()

        assert len(errors) == 2
        assert errors[1].startswith('Invalid tag')

    def test_validate_tags_duplicates(self, valid_manifest):
        valid_manifest['tags'].append('dup_tag')
        valid_manifest['tags'].append('duP_TaG')
        validator = ManifestValidator(valid_manifest)
        errors = validator.validate_normalize()

        assert len(errors) == 1
        assert errors[0].startswith('Some tags are more than once in the manifest')

    def test_known_targets_env(self, monkeypatch):
        monkeypatch.setenv(
            'IDF_COMPONENT_MANAGER_KNOWN_TARGETS', 'esp32,test,esp32s2,esp32s3,esp32c3,esp32h2,linux,esp32c2')
        result = known_targets()

        assert len(result) == 8
        assert 'test' in result

    def test_known_targets_idf(self, monkeypatch):
        monkeypatch.setenv(
            'IDF_PATH', os.path.join(os.path.dirname(os.path.realpath(__file__)), '..', 'fixtures', 'fake_idf'))
        result = known_targets()

        assert len(result) == 8
        assert 'test' in result

    def test_known_targets_default(self, monkeypatch):
        result = known_targets()

        assert result == DEFAULT_KNOWN_TARGETS

    def test_detect_unused_components(self, valid_manifest):
        project_requirements = [
            SolvedComponent(**{
                'name': 'example/cmp',
                'version': '*',
                'source': None
            }),
            SolvedComponent(**{
                'name': 'mag3110',
                'version': '*',
                'source': None
            })
        ]
        temp_path = tempfile.mkdtemp()
        managed_components_path = os.path.join(temp_path, 'managed_components')
        os.mkdir(managed_components_path)
        os.mkdir(os.path.join(managed_components_path, 'example__cmp'))
        with open(os.path.join(managed_components_path, 'example__cmp', HASH_FILENAME), 'w+') as f:
            f.write('e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855')
        os.mkdir(os.path.join(managed_components_path, 'mag3110'))
        with open(os.path.join(managed_components_path, 'mag3110', HASH_FILENAME), 'w+') as f:
            f.write('e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855')
        try:
            detect_unused_components(project_requirements, managed_components_path)
            assert len(os.listdir(managed_components_path)) == 2
            project_requirements = [SolvedComponent(**{'name': 'mag3110', 'version': '*', 'source': None})]
            detect_unused_components(project_requirements, managed_components_path)
            assert len(os.listdir(managed_components_path)) == 1
        finally:
            shutil.rmtree(temp_path)
