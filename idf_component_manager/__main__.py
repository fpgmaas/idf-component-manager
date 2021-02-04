#!/usr/bin/env python

import argparse
import os
import sys

from idf_component_tools.errors import FatalError

from .core import ComponentManager

KNOWN_ACTIONS = [
    'create-remote-component',
    'pack-component',
    'upload-component',
]


def main():
    parser = argparse.ArgumentParser(description='IDF component manager')
    parser.add_argument('command', choices=KNOWN_ACTIONS, help='Command to execute')
    parser.add_argument('--path', help='Working directory (default: current directory)', default=os.getcwd())
    parser.add_argument('--namespace', help='Namespace for the component. Can be set in config file.')
    parser.add_argument(
        '--service-profile',
        help='Profile for component service to use. By default profile named "default" will be used.',
        default='default')
    parser.add_argument('--name', help='Component name')
    parser.add_argument('--archive', help='Archive name for component upload')
    args = parser.parse_args()

    try:
        manager = ComponentManager(args.path)
        getattr(manager, str(args.command).replace('-', '_'))(vars(args))
    except FatalError as e:
        print(e)
        sys.exit(2)


if __name__ == '__main__':
    main()
