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

import errno
import logging
import os
import pprint

from steamosatomupd.image import Image
from steamosatomupd.manifest import Manifest
from steamosatomupd.update import UpdateCandidate, UpdatePath, Update

log = logging.getLogger(__name__)

IMAGE_MANIFEST_EXT = '.manifest.json'

# Atomic image things

RAUC_BUNDLE_EXT  = '.raucb'
CASYNC_STORE_EXT = '.castr'

def _get_rauc_update_path(image, images_dir, manifest_path):

    rauc_bundle = manifest_path[:-len(IMAGE_MANIFEST_EXT)] + RAUC_BUNDLE_EXT
    if not os.path.isfile(rauc_bundle):
        raise FileNotFoundError(errno.ENOENT, os.strerror(errno.ENOENT), rauc_bundle)

    casync_store =  manifest_path[:-len(IMAGE_MANIFEST_EXT)] + CASYNC_STORE_EXT
    if not os.path.isdir(casync_store):
        raise FileNotFoundError(errno.ENOENT, os.strerror(errno.ENOENT), casync_store)

    rauc_bundle_relpath = os.path.relpath(rauc_bundle, images_dir)

    return rauc_bundle_relpath

# Image pool

def _get_next_release(release, releases):
    """Get the next release in a list of releases.

    Releases are expected to be strings, sorted alphabetically, ie:

      [ 'brewmaster', 'clockwerk', 'doom' ]

    Cycling is not supported, ie. we won't go from 'zeus' to 'abaddon'.
    """

    try:
        idx = releases.index(release)
    except ValueError:
        return None

    try:
        next_release = releases[idx + 1]
    except IndexError:
        return None

    return next_release

def _get_update_candidates(candidates, image):
    """Get possible update candidates within a list.

    This is where we decide who are the valid update candidates for a
    given image. The valid candidates are:
    - images that are more recent than image
    - images that are either a checkpoint, either the latest image
    """

    latest = None
    checkpoints = []

    for c in candidates:
        if c.image <= image:
            continue

        if c.image.checkpoint:
            checkpoints.append(c)

        if not latest or c.image > latest.image:
            latest = c

    winners = checkpoints
    if latest and latest not in winners:
        winners.append(latest)

    return winners

class ImagePool:

    """An image pool

    An image pool is created by walking an image hierarchy, and
    looking for manifest files. It does not matter how the hierarchy
    is organized.

    The truth is that an image pool doesn't contain Image objects, but
    instead UpdateCandidate objects, which are simply a wrapper above
    images, with an additional update_path attribute.

    Internally, candidates are stored in the following structure:

    {
      product1: {
        release1: {
          variant1: {
            arch1: [ CANDIDATE1, CANDIDATE2, ... ],
            arch2: [ ... ]
          },
          variant2: { ...
          }, ...
        }, ...
      }, ...
    }

    """

    def __init__(self, images_dir, work_with_snapshots, want_unstable_images,
                 supported_products, supported_releases, supported_variants, supported_archs):

        # Make sure the images directory exist
        images_dir = os.path.abspath(images_dir)
        if not os.path.isdir(images_dir):
            raise RuntimeError("Images dir '{}' does not exist".format(images_dir))

        # Make sure releases are sorted
        if not sorted(supported_releases) == supported_releases:
            raise RuntimeError("Release list '{}' is not sorted".format(supported_releases))

        # If we work with snapshots, then obviously we want to consider unstable images
        # (as snapshots are treated as unstable images)
        if work_with_snapshots:
            want_unstable_images = True

        # Our variables
        self.images_dir = images_dir
        self.work_with_snapshots = work_with_snapshots
        self.want_unstable_images = want_unstable_images
        self.supported_products = supported_products
        self.supported_releases = supported_releases
        self.supported_variants = supported_variants
        self.supported_archs    = supported_archs

        # Create the hierarchy to store images
        data = {}
        for p in supported_products:
            data[p] = {}
            for r in supported_releases:
                data[p][r] = {}
                for v in supported_variants:
                    data[p][r][v] = {}
                    for a in supported_archs:
                        data[p][r][v][a] = []
        self.candidates = data

        # Populate the candidates dict
        log.debug("Walking the image tree: {}".format(images_dir))
        for root, dirs, files in os.walk(images_dir):
            [dirs.remove(d) for d in list(dirs) if d.endswith(".castr")]
            for f in files:
                # We're looking for manifest files
                if not f.endswith(IMAGE_MANIFEST_EXT):
                    continue

                manifest_path = os.path.join(root, f)

                # Create an image instance
                try:
                    manifest = Manifest.from_file(manifest_path)
                except Exception as e:
                    log.error("Failed to create image from manifest {}: {}".format(f, e))
                    continue

                image = manifest.image

                # Get an update path for this image
                try:
                    update_path = _get_rauc_update_path(image, images_dir, manifest_path)
                except Exception as e:
                    log.debug("Failed to get update path for manifest {}: {}".format(f, e))
                    continue

                # Get the list where this image belongs
                try:
                    candidates = self._get_candidate_list(image)
                except Exception as e:
                    log.debug("Discarded unsupported image {}: {}".format(f, e))
                    continue

                # Discard unstable images if we don't want them
                # TODO check the code to see if it's worth introducing image.is_unstable() for readability
                if not want_unstable_images and not image.is_stable():
                    log.debug("Discarded unstable image {}".format(f))
                    continue

                # Add image as an update candidate
                candidate = UpdateCandidate(image, update_path)
                candidates.append(candidate)
                log.debug("Update candidate added from manifest: {}".format(f))

    def __str__(self):
        return '\n'.join([
            'Images dir: {}'.format(self.images_dir),
            'Snapshots : {}'.format(self.work_with_snapshots),
            'Unstable  : {}'.format(self.want_unstable_images),
            'Products  : {}'.format(self.supported_products),
            'Releases  : {}'.format(self.supported_releases),
            'Variants  : {}'.format(self.supported_variants),
            'Archs     : {}'.format(self.supported_archs),
            'Candidates: (see below)',
            '{}'.format(pprint.pformat(self.candidates))
        ])

    def _get_candidate_list(self, image, release=None):
        """Return the list of update candidates that an image belong to

        The optional 'release' field is used to override the image release.

        This method also does sanity check, to ensure the image is supported.
        We might raise exceptions if the image is not supported.
        """

        # Mixing snapshot and non-snapshot images is not allowed
        if image.version and self.work_with_snapshots:
            raise ValueError("Image has a version, however we support only snapshots")
        if not image.version and not self.work_with_snapshots:
            raise ValueError("Image is a snapshot, however we support only versions")

        # Get the image list according to image details
        try:
            p = image.product
            if release:
                r = release
            else:
                r = image.release
            v = image.variant
            a = image.arch
            candidates = self.candidates[p][r][v][a]
        except KeyError as e:
            raise ValueError("Image is not supported: {}".format(e))

        return candidates

    def get_updates_for_release(self, image, release):
        """Get a list of update candidates for a given release

        Return an UpdatePath object, or None if no updates available.
        """

        try:
            all_candidates = self._get_candidate_list(image, release=release)
        except ValueError:
            return None

        candidates = _get_update_candidates(all_candidates, image)
        if not candidates:
            return None

        return UpdatePath(release, candidates)

    def get_updates(self, image):
        """Get updates

        We look for update candidates in the same release as the image,
        and in the next release (if any).

        Return an Update object, or None if no updates available.
        """

        curr_release = image.release
        minor_update = self.get_updates_for_release(image, curr_release)

        next_release =  _get_next_release(curr_release, self.supported_releases)
        major_update = None
        if next_release:
            major_update = self.get_updates_for_release(image, next_release)

        if minor_update or major_update:
            return Update(minor_update, major_update)
        else:
            return None
