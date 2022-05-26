# SPDX-License-Identifier: LGPL-2.1+
#
# Copyright © 2018-2020 Collabora Ltd
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
import signal
import sys
import time

from threading import Lock, Thread
from steamosatomupd.image import Image
from steamosatomupd.imagepool import ImagePool

from flask import Flask, request, Response

logging.basicConfig(format='%(levelname)s:%(filename)s:%(lineno)s: %(message)s')
log = logging.getLogger(__name__)

# Default config
DEFAULT_FLASK_HOSTNAME = 'localhost'
DEFAULT_FLASK_PORT = 5000
DEFAULT_SERVE_UNSTABLE = False

# Global
server = None

#
# Flask server
#

app = Flask(__name__)


@app.route('/')
def updates():

    """Handle requests from client"""

    log.debug("Request: {}".format(request.args))

    global server
    try:
        data = server.get_update(request.args)
    except (ValueError, KeyError) as err:
        log.debug('Malformed request: {}'.format(err))
        return Response("Malformed request", status=400)

    log.debug("Reply: {}".format(data))

    return json.dumps(data)

#
# Update server
#

def dump_handler(signum, frame):

    global server
    if not server:
        return

    server.start_dump()

def reload_handler(signum, frame):

    global server
    if not server:
        return

    server.start_reload()

class UpdateServer:

    def get_update(self, data):

        # Make an image out of the request arguments. An exception might be
        # raised, which results in returning 400 to the client.
        image = Image.from_dict(request.args)
        if not image:
            return ''

        # Get update candidates
        self.lock.acquire()
        update = self.image_pool.get_updates(image)
        self.lock.release()
        if not update:
            return ''

        # Return to client
        data = update.to_dict()

        return data

    def dump_worker(self):

        self.dump()
        self.dump_thread = None

    def start_dump(self):

        if self.dump_thread:
            return

        thread = Thread(name='dump', target=UpdateServer.dump_worker,
                        args=(self,))
        thread.start()
        self.dump_thread = thread

    def reload_worker(self):

        print("Creating the pool of image, this may take a while...")
        start = time.time()
        self.reload()
        end = time.time()
        print("Image pool created in {0:.3f} seconds".format(end - start))
        self.reload_thread = None

    def start_reload(self):

        if self.reload_thread:
            return

        thread = Thread(name='reload', target=UpdateServer.reload_worker,
                        args=(self,))
        thread.start()
        self.reload_thread = thread

    def dump(self):

        self.lock.acquire()
        print("--- Image Pool ---")
        print('{}'.format(self.image_pool))
        print("------------------")
        sys.stdout.flush()
        self.lock.release()

    def reload(self):

        image_pool = ImagePool(self.config['Images']['PoolDir'],
                               self.config['Images'].getboolean('Snapshots'),
                               self.config['Images'].getboolean('Unstable'),
                               self.config['Images']['Products'].split(),
                               self.config['Images']['Releases'].split(),
                               self.config['Images']['Variants'].split(),
                               self.config['Images']['Archs'].split())
        self.lock.acquire()
        self.image_pool = image_pool
        self.lock.release()
        self.dump()

    def __init__(self):

        # Arguments

        parser = argparse.ArgumentParser(
            description = "SteamOS Update Server")
        parser.add_argument('-c', '--config', metavar='FILE', required=True,
            help="configuration file")
        parser.add_argument('-d', '--debug', action='store_true',
            help="show debug messages")

        args = parser.parse_args()

        if args.debug:
            logging.getLogger().setLevel(logging.DEBUG)

        # Config file

        log.debug("Parsing config from file: {}".format(args.config))

        config = configparser.ConfigParser()

        config.read_dict({
            'Server': {
                'Host': DEFAULT_FLASK_HOSTNAME,
                'Port': DEFAULT_FLASK_PORT,
            },
            'Images': {
                'Unstable': DEFAULT_SERVE_UNSTABLE,
            }})

        with open(args.config, 'r') as f:
            config.read_file(f)

        # Create image pool

        try:
            images_dir = config['Images']['PoolDir']
            snapshots = config['Images'].getboolean('Snapshots')
            unstable = config['Images'].getboolean('Unstable')
            products = config['Images']['Products'].split()
            releases = config['Images']['Releases'].split()
            variants = config['Images']['Variants'].split()
            archs    = config['Images']['Archs'].split()
        except KeyError:
            log.error("Please provide a valid configuration file")
            sys.exit(1)

        # We strongly expect releases to be an ordered list. We could sort
        # it ourselves, but we can also just refuse an unsorted list, and
        # take this chance to warn user that we care about releases being
        # ordered (because we might use release names to compare to image,
        # and a clockwerk image (3.x) is below a doom (4.x) image).

        if sorted(releases) != releases:
            log.error("Releases in configuration file must be ordered!")
            sys.exit(1)

        self.config = config
        self.lock = Lock()
        self.reload()

        # Handle signals

        signal.signal(signal.SIGUSR1, dump_handler)
        signal.signal(signal.SIGUSR2, reload_handler)

    def __del__(self):

        if self.dump_thread:
            self.dump_thread.cancel()

        if self.reload_thread:
            self.reload_thread.cancel()

    def run(self):

        hostname = self.config['Server']['Host']
        port = int(self.config['Server']['Port'])
        app.run(host=hostname, port=port)


    image_pool = None
    lock = None
    dump_thread = None
    reload_thread = None

def main():
    global server
    server = UpdateServer()
    server.run()
