import filecmp
import os
from io import open
from pathlib import Path

import pytest

from idf_component_manager.dependencies import is_solve_required
from idf_component_tools.errors import LockError
from idf_component_tools.lock import LockManager
from idf_component_tools.manifest import (
    ComponentVersion, Manifest, ManifestManager, ProjectRequirements, SolvedComponent, SolvedManifest)
from idf_component_tools.manifest.if_parser import parse_if_clause
from idf_component_tools.sources import IDFSource, WebServiceSource

dependencies = {
    'idf': {
        'version': '4.4.4',
        'source': {
            'type': 'idf'
        }
    },
    'espressif/test_cmp': {
        'version': '1.2.7',
        'component_hash': 'f0e4c2f76c58916ec258f246851bea091d14d4247a2fc3e18694461b1816e13b',
        'source': {
            'service_url': 'https://repo.example.com',
            'type': 'service'
        }
    }
}

MANIFEST_HASH = 'e6790d541ef7d404b4583ee601c9c98a836810cedc486d91660b1e17b59a7498'
valid_lock_path = os.path.join(
    os.path.dirname(os.path.realpath(__file__)),
    'fixtures',
    'locks',
    'dependencies.lock',
)
manifest_path = os.path.join(
    os.path.dirname(os.path.realpath(__file__)),
    'fixtures',
    'idf_component.yml',
)


class TestLockManager(object):
    def test_load_valid_lock(self):
        parser = LockManager(valid_lock_path)

        lock = parser.load()
        assert parser.exists()

        test_cmp = [cmp for cmp in lock.dependencies if cmp.name == 'espressif/test_cmp'][0]
        assert (test_cmp.source.service_url == 'https://repo.example.com')

    def test_lock_dump_with_solution(self, tmp_path, monkeypatch):
        monkeypatch.setenv('IDF_TARGET', 'esp32')
        lock_path = os.path.join(str(tmp_path), 'dependencies.lock')

        lock = LockManager(lock_path)
        manifest = ManifestManager(manifest_path, name='test').load()
        components = [
            SolvedComponent(
                name='idf',
                version=ComponentVersion('4.4.4'),
                source=IDFSource({}),
            ),
            SolvedComponent(
                name='espressif/test_cmp',
                version=ComponentVersion('1.2.7'),
                source=WebServiceSource({'service_url': 'https://repo.example.com'}),
                component_hash='f0e4c2f76c58916ec258f246851bea091d14d4247a2fc3e18694461b1816e13b',
            ),
        ]

        solution = SolvedManifest(components, manifest_hash=manifest.manifest_hash)
        lock.dump(solution)

        assert filecmp.cmp(lock_path, valid_lock_path, shallow=False)

    def test_lock_dump_with_dictionary(self, tmp_path, monkeypatch):
        monkeypatch.setenv('IDF_TARGET', 'esp32')
        lock_path = os.path.join(str(tmp_path), 'dependencies.lock')
        parser = LockManager(lock_path)
        solution = SolvedManifest.fromdict(
            dict([
                ('version', '1.0.0'),
                ('dependencies', dependencies),
                ('manifest_hash', MANIFEST_HASH),
            ]))

        parser.dump(solution)

        assert filecmp.cmp(lock_path, valid_lock_path, shallow=False)

    def test_lock_dump(self, tmp_path, monkeypatch):
        monkeypatch.setenv('IDF_TARGET', 'esp32')
        lock_path = os.path.join(str(tmp_path), 'dependencies.lock')
        parser = LockManager(lock_path)
        solution = parser.load()
        solution.manifest_hash = MANIFEST_HASH
        for (name, details) in dependencies.items():
            details['name'] = name
            solution.dependencies.append(SolvedComponent.fromdict(details))

        parser.dump(solution)

        assert filecmp.cmp(lock_path, valid_lock_path, shallow=False)

    def test_load_invalid_lock(self, capsys, monkeypatch):
        monkeypatch.setenv('IDF_TARGET', 'esp32')
        lock_path = os.path.join(
            os.path.dirname(os.path.realpath(__file__)),
            'fixtures',
            'locks',
            'invalid_dependencies.lock',
        )

        parser = LockManager(lock_path)
        assert parser.exists()

        with pytest.raises(LockError) as e:
            parser.load()

        assert e.type == LockError

    def test_minimal_lock(self, tmp_path, monkeypatch):
        monkeypatch.setenv('IDF_TARGET', 'esp32')
        lock_path = os.path.join(str(tmp_path), 'dependencies.lock')
        parser = LockManager(lock_path)
        solution = SolvedManifest.fromdict(dict([
            ('version', '1.0.0'),
            ('manifest_hash', MANIFEST_HASH),
        ]))

        parser.dump(solution)
        loaded_solution = parser.load()

        assert solution.manifest_hash == loaded_solution.manifest_hash

        with open(lock_path) as f:
            assert f.read() == 'manifest_hash: {}\ntarget: esp32\nversion: 1.0.0\n'.format(solution.manifest_hash)

    def test_empty_lock_file(self, tmp_path):
        lock_path = os.path.join(str(tmp_path), 'dependencies.lock')
        Path(lock_path).touch()

        solution = LockManager(lock_path).load()

        assert solution.manifest_hash is None

    def test_change_manifest_file_idf_version(self, monkeypatch):
        monkeypatch.setenv('IDF_TARGET', 'esp32')
        manifest = Manifest.fromdict({'dependencies': {'idf': '4.4.0'}}, name='test_manifest')
        project_requirements = ProjectRequirements([manifest])
        solution = SolvedManifest.fromdict(
            dict(
                [
                    ('version', '1.0.0'),
                    ('dependencies', {
                        'idf': {
                            'component_hash': None,
                            'source': {
                                'type': 'idf'
                            },
                            'version': '4.2.0'
                        }
                    }),
                    ('manifest_hash', '3a22a5a1ff0fc96e81492ebedbf1885cb8e5747858a37430a2aa8cde611223df'),
                ]))

        monkeypatch.setenv('IDF_VERSION', '4.4.0')
        assert is_solve_required(project_requirements, solution)  # Different idf version

        solution.manifest_hash = 'bff084ca418bd07bbb3f7b0a6713f45e802be72a006a5f30ac70ac755639683c'
        assert is_solve_required(project_requirements, solution)  # Wrong manifest hash

        monkeypatch.setenv('IDF_VERSION', '4.2.0')
        solution.manifest_hash = '3a22a5a1ff0fc96e81492ebedbf1885cb8e5747858a37430a2aa8cde611223df'
        assert not is_solve_required(project_requirements, solution)

    def test_change_manifest_file_dependencies_rules(self, monkeypatch):
        monkeypatch.setenv('IDF_TARGET', 'esp32')
        monkeypatch.setenv('IDF_VERSION', '4.4.0')
        manifest_dict = {
            'dependencies': {
                'foo': {
                    'version': '*',
                    'rules': [
                        parse_if_clause('idf_version > 4'),
                    ]
                }
            }
        }
        solution = SolvedManifest.fromdict(
            dict(
                [
                    ('version', '1.0.0'),
                    (
                        'dependencies', {
                            'foo': {
                                'component_hash': 'foo',
                                'source': {
                                    'type': 'local'
                                },
                                'version': '1.0.0',
                            }
                        }),
                    ('manifest_hash', 'f0b3e4408d768a03a17e09a91019f492fe053daaea11007f79d7cea3636d3945'),
                ]))

        monkeypatch.setenv('IDF_VERSION', '5.0.0')
        manifest_dict['dependencies']['foo']['rules'] = [parse_if_clause('idf_version > 4')]
        manifest = Manifest.fromdict(manifest_dict, name='test_manifest')
        project_requirements = ProjectRequirements([manifest])
        assert not is_solve_required(project_requirements, solution)

        monkeypatch.setenv('IDF_VERSION', '3.0.0')
        manifest_dict['dependencies']['foo']['rules'] = [parse_if_clause('idf_version > 4')]
        manifest = Manifest.fromdict(manifest_dict, name='test_manifest')
        project_requirements = ProjectRequirements([manifest])
        assert is_solve_required(project_requirements, solution)

    def test_change_manifest_file_targets(self, monkeypatch):
        monkeypatch.setenv('IDF_TARGET', 'esp32')
        manifest = Manifest.fromdict({'targets': ['esp32']}, name='test_manifest')
        solution = SolvedManifest.fromdict(
            dict(
                [
                    ('version', '1.0.0'),
                    ('manifest_hash', 'c9c3b34bbdea9ab2d265d603d459fd4fd9d6d9e26eb454e31fd002d4fc8f49fa'),
                ]))

        manifest.targets = ['esp32s2', 'esp32s3']
        project_requirements = ProjectRequirements([manifest])
        assert is_solve_required(project_requirements, solution)  # Different idf target

        manifest.targets = ['esp32']
        project_requirements = ProjectRequirements([manifest])
        assert not is_solve_required(project_requirements, solution)  # change it back

    def test_empty_manifest_file(self, monkeypatch):
        monkeypatch.setenv('IDF_TARGET', 'esp32')
        solution = SolvedManifest.fromdict(
            dict(
                [
                    ('version', '1.0.0'),
                    ('manifest_hash', '12ce0230205ae425485ae16eb90990e01b0582e262c9d72290955fe09cb1adfe'),
                ]))

        manifest = Manifest.fromdict({'targets': ['esp32']}, name='test_manifest')
        project_requirements = ProjectRequirements([manifest])
        assert is_solve_required(project_requirements, solution)  # Different idf target

        manifest = Manifest.fromdict({}, name='test_manifest')
        project_requirements = ProjectRequirements([manifest])
        assert not is_solve_required(project_requirements, solution)  # change it back
