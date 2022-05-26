#!/usr/bin/env python3
# encoding: utf-8

# Starts a devkit title directly - that is, outside of steam
# For instance, a dev upload of the steam client itself

import sys
import os
import subprocess
import shlex
import stat
import argparse
import logging

try:
    import steam_devkit.utils
except:
    # find the module folder
    top_level = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
    if os.path.isdir(os.path.join(top_level, 'steam_devkit')):
        # development case
        sys.path.append(top_level)
        import steam_devkit.utils
    else:
        # packaged case
        sys.path.append(os.path.join(top_level, 'hooks'))
        import steam_devkit.utils

logger = logging.getLogger(os.path.realpath(__file__))
logging.getLogger().setLevel(logging.INFO)
logging.basicConfig()

if __name__ == '__main__':
    logger.info('%r', sys.argv)

    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument('name')
    conf, unknown_args = parser.parse_known_args()

    settings = steam_devkit.utils.load_settings(conf.name)
    logger.info('settings: %r', settings)
    cwd = os.path.join(os.getenv("HOME"), "devkit-game", conf.name)
    logger.info('cwd: %r', cwd)
    argv = steam_devkit.utils.obtain_argv(conf.name, None)
    logger.info('argv: %r', argv)

    if len(argv) > 1:
        args = argv
    else:
        args = shlex.split(argv[0])
    logger.info('%r', args)

    sys.stdout.flush()
    sys.stderr.flush()

    p = subprocess.Popen(args, cwd=cwd, close_fds=True)

    logger.info('starting pid %d', p.pid)
    sys.stderr.flush()

    p.communicate()
    sys.stdout.flush()
    sys.stderr.flush()

    logger.info('pid %d exited with code %d', p.pid, p.returncode)
