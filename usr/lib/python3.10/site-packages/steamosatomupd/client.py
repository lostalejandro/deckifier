# SPDX-License-Identifier: LGPL-2.1+
#
# Copyright © 2018-2021 Collabora Ltd
#
# This package is free software; you can redistribute it and/or
# modify it under the terms of the GNU Lesser General Public
# License as published by the Free Software Foundation; either
# version 2.1 of the License, or (at your option) any later version.
#
# This package is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
# Lesser General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public
# License along with this package.  If not, see
# <http://www.gnu.org/licenses/>.

import argparse
import configparser
import json
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import netrc
import urllib.parse
import urllib.request
import multiprocessing
from pathlib import Path

from steamosatomupd.image import Image
from steamosatomupd.manifest import Manifest
from steamosatomupd.update import Update, UpdatePath

logging.basicConfig(format='%(levelname)s:%(filename)s:%(lineno)s: %(message)s')
log = logging.getLogger(__name__)

# Hard-coded defaults
UPDATE_FILENAME = 'update.json'

# Default args
DEFAULT_CONFIG_FILE = '/etc/steamos-atomupd/client.conf'

# Default config
DEFAULT_MANIFEST_FILE = '/etc/steamos-atomupd/manifest.json'
DEFAULT_RUNTIME_DIR   = '/run/steamos-atomupd'


def do_progress():
    """Print the progression using a journald"""

    c = subprocess.Popen(['journalctl', '--unit=rauc.service', '--since=now',
                          '--output=cat', '--follow'],
                         stderr=subprocess.STDOUT,
                         stdout=subprocess.PIPE,
                         universal_newlines=True)

    using_desync = is_desync_in_use()
    slot = ""
    while c.poll() is None:
        line = c.stdout.readline().rstrip()
        log.debug(line)

        words = line.split()
        if len(words) == 0:
            continue
        elif words[0] == "installing" and words[2] == "started":
            print("%d%%" % 0)
        elif words[0] == "installing" and words[2] == "finished":
            print("%d%%" % 100)
        elif words[0] == "installing" and words[2] == "succeeded":
            break
        elif words[0] == "installing" and words[2] == "failed:":
            break
        elif using_desync:
            if words[0].endswith('%') and len(words) < 3:
                print(line.strip())
        else:
            if words[0] == "Slot":
                slot = os.path.basename(os.path.splitext(words[6])[0])
                slot = os.path.splitext(slot)[0]
            elif slot == "rootfs" and ' '.join(words[0:-1]) == "seeding...":
                print("%d%%" % ((float(words[-1][:-1]) * 25 * 0.9 / 100) + 5))
            elif slot == "rootfs" and ' '.join(words[0:-1]) == "downloading chunks...":
                print("%d%%" % ((float(words[-1][:-1]) * 75 * 0.9 / 100) + 5 + (25 * 0.9)))
            elif words[0] == "installing" and ' '.join(words[2:]) == "All slots updated":
                print("%d%%" % 95)
        sys.stdout.flush()

    c.terminate()


def download_update_file(url, image):
    """Download an update file from the server

    The parameters for the request are the details of the image that
    the caller is running.

    The server is expected to return a JSON string, which is then parsed
    by the client, in order to validate it. Then it's printed out to a
    temporary file, and the filename is returned.

    If the server returns an empty string, then we return None.

    Exceptions might be raised here and there...
    """

    netrcfile = os.path.expanduser("~/.netrc") 
    if os.path.isfile(netrcfile):
        host = urllib.parse.urlparse(url).netloc
        auth = netrc.netrc(netrcfile).authenticators(host)
        if auth:
            manager = urllib.request.HTTPPasswordMgrWithDefaultRealm()
            manager.add_password(None, host, auth[0], auth[2])
            handler = urllib.request.HTTPBasicAuthHandler(manager)
            opener = urllib.request.build_opener(handler)
            urllib.request.install_opener(opener)

    with urllib.request.urlopen(url) as response:
        jsonstr = response.read()

    if not jsonstr:
        return None

    update_data = json.loads(jsonstr)
    update = Update.from_dict(update_data)

    with tempfile.NamedTemporaryFile(mode='w', delete=False) as f:
        f.write(update.to_string())

    return f.name


def create_index(runtime_dir: Path, replace: bool) -> Path:
    """ Re-create index file, and its symlink, for the rootfs

    Returns the index file path.
    """

    rootfs_index = runtime_dir / 'rootfs.caibx'
    if rootfs_index.exists() and not replace:
        return rootfs_index

    rootfs_index.unlink(missing_ok=True)

    rootfs_dir = get_rootfs_device()
    c = subprocess.run(['desync', 'make', rootfs_index, rootfs_dir],
                       stderr=subprocess.STDOUT,
                       stdout=subprocess.PIPE,
                       universal_newlines=True)

    if c.returncode != 0:
        raise RuntimeError(
            "Failed to create the index file for the active partition rootfs: {}: {}".format(
                c.returncode, c.stdout))

    # Create a symlink next to the index as required by `desync extract`.
    # We can pass only the index filename to the command.
    rootfs_symlink = runtime_dir / 'rootfs'
    rootfs_symlink.unlink(missing_ok=True)
    os.symlink(rootfs_dir, rootfs_symlink)

    return rootfs_index


def do_update(url: str, runtime_dir: Path, quiet: bool) -> None:
    """Update the system"""

    if is_desync_in_use():
        # TODO if we skip invalid seeds in Desync we can avoid recreating
        # the seed index
        create_index(runtime_dir, True)

    # Remount /tmp with max memory and inodes number
    #
    # This is possible as long as /tmp is backed by a tmpfs. We need
    # this precaution as casync makes a heavy use of its tmpdir in /tmp.
    # It needs enough memory to store the chunks it downloads, and it
    # also needs A LOT of inodes.

    c = subprocess.run(['mount',
                        '-o', 'remount,size=100%,nr_inodes=1g',
                        '/tmp', '/tmp'],
                       stderr=subprocess.STDOUT,
                       stdout=subprocess.PIPE,
                       universal_newlines=True)

    if c.returncode != 0:
        log.warning("Failed to remount /tmp: {}: {}".format(c.returncode, c.stdout))
        # Let's keep going and hope that /tmp can handle the load

    # Let's update now

    if not quiet:
        p = multiprocessing.Process(target=do_progress)
        p.start()
    c = subprocess.run(['rauc', 'install', url],
                       stderr=subprocess.STDOUT,
                       stdout=subprocess.PIPE,
                       universal_newlines=True)
    if not quiet and p.is_alive():
        p.join(5)
        if p.is_alive():
            p.terminate()

    if c.returncode != 0:
        raise RuntimeError("Failed to install bundle: {}: {}".format(c.returncode, c.stdout))


def estimate_download_size(runtime_dir: Path, update_url: str,
                           buildid: str, required_buildid: str) -> int:
    """Estimate the download size for the provided buildid.

    The estimation will be based against the required_buildid or, if not set,
    against the current active partition.

    Returns the estimated size in Bytes or zero if we were not able to estimate
    the download size.
    """
    if not is_desync_in_use():
        return 0

    destination = runtime_dir / buildid

    # If we already extracted this update bundle, don't do it again
    if not destination.exists():
        c = subprocess.run(['rauc', 'extract', update_url, destination],
                           stderr=subprocess.STDOUT,
                           stdout=subprocess.PIPE,
                           text=True)

        if c.returncode != 0:
            # Estimating the download size is not a critical operation.
            # If it fails we try to continue anyway.
            log.warning("Failed to extract bundle: {}: {}".format(c.returncode, c.stdout))
            return 0

    update_index = destination / 'rootfs.img.caibx'
    if not update_index.exists():
        log.warning("The extracted bundle doesn't have the expected 'rootfs.img.caibx' file")
        return 0

    if required_buildid:
        seed = runtime_dir / required_buildid
        if not seed.exists():
            log.debug("Unable to estimate the download size because the "
                      "required base image bundle is missing")
            return 0
    else:
        # This image can be installed directly, use the current active
        # partition as a seed
        seed = create_index(runtime_dir, False)

    c = subprocess.run(['desync', 'info', '--seed', seed, update_index],
                       capture_output=True,
                       text=True)

    if c.returncode != 0:
        log.warning(
            "Failed to gather information about the update: {}: {}".format(
                c.returncode,
                c.stdout
            )
        )
        return 0

    index_info = json.loads(c.stdout)
    return index_info.get("dedup-size-not-in-seed", 0)


def ensure_estimated_download_size(update_path: UpdatePath,
                                   images_url: str,
                                   runtime_dir: Path) -> UpdatePath:
    """Estimate the download size for all the candidates in update_path

    If an estimation is already present, it will not be recalculated.

    Returns an UpdatePath object that includes the estimated download sizes.
    """
    if not update_path:
        return update_path
    required_buildid = ""
    for i, candidate in enumerate(update_path.candidates):
        if candidate.image.estimated_size != 0:
            # If the server already provided an estimation for the
            # download size, we don't need to recalculate it
            continue
        update_url = urllib.parse.urljoin(images_url, candidate.update_path)
        update_path.candidates[i].image.estimated_size = estimate_download_size(
            Path(runtime_dir),
            update_url,
            str(candidate.image.buildid),
            required_buildid
        )
        required_buildid = candidate.image.buildid

    return update_path


def get_rootfs_device() -> Path:
    """ Get the rootfs device path from RAUC """

    c = subprocess.run(['rauc', 'status', '--output-format=json'],
                       capture_output=True,
                       text=True)

    if c.returncode != 0:
        raise RuntimeError(
            'Failed to get RAUC status output: {}: {}'.format(c.returncode,
                                                              c.stdout))

    status = json.loads(c.stdout)
    boot_primary = status['boot_primary']
    if not boot_primary:
        raise RuntimeError("RAUC cannot determine the booted slot")

    for s in status['slots']:
        if boot_primary in s:
            return Path(s[boot_primary]['device'])

    raise RuntimeError('Failed to parse the RAUC status output')


def is_desync_in_use() -> bool:
    """ Use RAUC configuration to check if Desync will be used """

    rauc_conf_path = '/etc/rauc/system.conf'

    config = configparser.ConfigParser()
    config.read(rauc_conf_path)

    if 'casync' not in config:
        return False

    return config['casync'].getboolean('use-desync', fallback=False)


class UpdateClient:

    def __init__(self):
        pass

    def run(self):

        # Arguments

        parser = argparse.ArgumentParser(
            description = "SteamOS Update Client")
        parser.add_argument('-c', '--config',
            metavar='FILE', default=DEFAULT_CONFIG_FILE,
            help="configuration file (default: {})".format(DEFAULT_CONFIG_FILE))
        parser.add_argument('-q', '--quiet', action='store_true',
            help="hide output")
        parser.add_argument('-d', '--debug', action='store_true',
            help="show debug messages")
        parser.add_argument('--query-only', action='store_true',
            help="only query if an update is available")
        parser.add_argument('--estimate-download-size', action='store_true',
            help="Include in the update file the estimated download size for "
                 "each image candidate")
        parser.add_argument('--manifest-file',
            metavar='FILE', # can't use default= here, see below
            help="manifest file (default: {})".format(DEFAULT_MANIFEST_FILE))
        parser.add_argument('--mk-manifest-file', action='store_true',
            help="don't use existing manifest file, make one instead")
        parser.add_argument('--update-file',
            help="update from given file, instead of downloading it from server")
        parser.add_argument('--update-from-url',
            help="update to a specific RAUC bundle image")
        parser.add_argument('--update-version',
            help="update to a specific buildid version. It will fail if either "
                 "the update file doesn't contain this buildid or if it "
                 "requires a base image that is newer than the current one")
        parser.add_argument('--variant',
            help="use this 'variant' value instead of the one parsed from the "
                 "manifest file")

        args = parser.parse_args()

        if args.debug:
            logging.getLogger().setLevel(logging.DEBUG)

        # Config file

        log.debug("Parsing config from file: {}".format(args.config))

        config = configparser.ConfigParser()

        config.read_dict({
            'Host': {
                # can't use default for 'Manifest' here, see below
                'RuntimeDir': DEFAULT_RUNTIME_DIR,
            }})

        with open(args.config, 'r') as f:
            config.read_file(f)

        assert config['Server']['QueryUrl']
        assert config['Server']['ImagesUrl']

        runtime_dir = config['Host']['RuntimeDir']
        if not os.path.isdir(runtime_dir):
            log.debug("Creating runtime dir {}".format(runtime_dir))
            os.makedirs(runtime_dir)

        if args.update_from_url:
            log.debug("Installing an update from the given URL")
            try:
                do_update(args.update_from_url, Path(runtime_dir), args.quiet)
            except Exception as e:
                log.error("Failed to install update from URL: {}".format(e))
                return -1
            return 0

        # Handle the manifest file logic

        if args.mk_manifest_file:
            manifest_file = None
            log.debug("Not using any manifest file, making one instead")
        else:
            if args.manifest_file:
                manifest_file = args.manifest_file
            elif config.has_option('Host', 'Manifest'):
                manifest_file = config['Host']['Manifest']
            else:
                manifest_file = DEFAULT_MANIFEST_FILE
            log.debug("Using manifest file '{}'".format(manifest_file))

        # Download update file, unless one is given in args

        if args.update_file:
            update_file = args.update_file
        else:
            update_file = os.path.join(runtime_dir, UPDATE_FILENAME)

            # Get details about the current image
            if manifest_file:
                manifest = Manifest.from_file(manifest_file)
                image = manifest.image
            else:
                image = Image.from_os()

            # Replace the variant value with the one provided as an argument
            if args.variant:
                image.variant = args.variant

            # Download the update file to a tmp file
            url = config['Server']['QueryUrl'] + '?' + urllib.parse.urlencode(image.to_dict())
            try:
                log.debug("Downloading update file {}".format(url))
                tmpfile = download_update_file(url, image)
            except Exception as e:
                log.error("Failed to download update file: {}".format(e))
                return -1

            # Handle the result
            if tmpfile:
                log.info("Server returned something, guess an update is available")
                shutil.move(tmpfile, update_file)
            else:
                log.info("Server returned nothing, guess we're up to date")
                if os.path.exists(update_file):
                    os.remove(update_file)
                return 0

        # Parse update file

        log.debug("Parsing update file: {}".format(update_file))

        with open(update_file, 'r') as f:
            update_data = json.load(f)

        update = Update.from_dict(update_data)

        if not update:
            log.debug("No update candidate, even though the server returned something")
            log.debug("This is very unexpected, please inspect '{}'".format(update_file))
            return -1

        # Log a bit

        def log_update(upd):
            log.debug("An update is available for release '{}'".format(upd.release))
            n_imgs = len(upd.candidates)
            if n_imgs > 0:
                cand = upd.candidates[0]
                img = cand.image
                log.debug("> going to version: {} ({})".format(img.version, img.buildid))
                log.debug("> update path: {}".format(cand.update_path))
            if n_imgs > 1:
                cand = upd.candidates[-1]
                img = cand.image
                log.debug("> final destination: {} ({})".format(img.version, img.buildid))
                log.debug("> total number of updates: {}".format(n_imgs))

        if update.minor:
            log_update(update.minor)

        if update.major:
            log_update(update.major)

        images_url = config['Server']['ImagesUrl']
        if not images_url.endswith('/'):
            images_url += '/'

        if args.estimate_download_size:
            update.minor = ensure_estimated_download_size(update.minor,
                                                          images_url,
                                                          Path(runtime_dir))
            update.major = ensure_estimated_download_size(update.major,
                                                          images_url,
                                                          Path(runtime_dir))

        # Bail out if needed

        if args.query_only:
            if not args.quiet:
                print(json.dumps(update.to_dict(), indent=2))
            os.remove(update_file)
            return 0

        # Apply update

        # Ensure we're running from a read-only system

        # TODO We probably want to check that the current release matches
        #      our current release, just as a safety check
        # TODO If we're supposed to run unattended, should we validate that?
        #      (like, there should be no X/Wayland or something)
        # TODO Should we check that the versions proposed by the server are
        #      above our own version, or should we trust the server blindly?

        update_path = ""
        if update.major:
            candidate = update.major.candidates[0]
            if not args.update_version or args.update_version == str(candidate.image.buildid):
                update_path = candidate.update_path

        if not update_path and update.minor:
            candidate = update.minor.candidates[0]
            if not args.update_version or args.update_version == str(candidate.image.buildid):
                update_path = candidate.update_path

        if not update_path:
            if args.update_version:
                log.error("The requested update version is not a valid option")
                return -1
            else:
                log.debug("No update")
                return 0

        log.debug("Applying update NOW")

        try:
            update_url = urllib.parse.urljoin(images_url, update_path)
            do_update(update_url, Path(runtime_dir), args.quiet)
        except Exception as e:
            log.error("Failed to install update file: {}".format(e))
            return -1

        return 0



def main():
    client = UpdateClient()
    ret = client.run()
    sys.exit(abs(ret))
