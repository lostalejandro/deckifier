# SPDX-License-Identifier: LGPL-2.1+
#
# Copyright © 2018-2019 Collabora Ltd
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

import json

from steamosatomupd.image import Image

class UpdateCandidate:

    """An update candidate

    An update candidate is simply an image with an update path.

    -- This is the dataclass definition (requires python >= 3.7) --
    image: Image
    update_path: str
    """

    def __init__(self, image, update_path):
        self.image = image
        self.update_path = update_path

    @classmethod
    def from_dict(cls, data):
        """Create an UpdateCandidate from a dictionary

        Raise exceptions if the dictionary doesn't contain the expected keys,
        or if values are not valid.
        """

        image = Image.from_dict(data['image'])
        update_path = data['update_path']
        return cls(image, update_path)

    def to_dict(self):
        """Export an UpdateCandidate to a dictionary"""

        data = {}
        data['image'] = self.image.to_dict()
        data['update_path'] = self.update_path

        return data

    def __repr__(self):
        return "{}, {}".format(self.image, self.update_path)


class UpdatePath:

    """An update path

    An update path is a list of update candidates, sorted. It's created for
    a particular image, and it represents all the updates that this image
    should apply in order to be up-to-date.

    An update path can be imported/exported as a dictionary:

      {
        'release': 'clockwerk',
        'candidates': [ CANDIDATE1, CANDIDATE2, ... ]
      }

    -- This is the dataclass definition (requires python >= 3.7) --
    release: str
    candidates: List[UpdateCandidate]
    """

    def __init__(self, release, candidates):
        self.release = release
        self.candidates = []

        if not candidates:
            return

        self.candidates = sorted(candidates, key=lambda c: c.image)

    @classmethod
    def from_dict(cls, data):
        """Create an UpdatePath from a dictionary

        Raise exceptions if the dictionary doesn't contain the expected keys,
        or if values are not valid.
        """

        release = data['release']
        candidates = []

        for cdata in data['candidates']:
            candidate = UpdateCandidate.from_dict(cdata)
            candidates.append(candidate)

        return cls(release, candidates)

    def to_dict(self):
        """Export an UpdatePath to a dictionary"""

        array = []
        for c in self.candidates:
            cdata = c.to_dict()
            array.append(cdata)

        data = {}
        data['release'] = self.release
        data['candidates'] = array

        return data

class Update:

    """An update

    An update lists the update paths possible for an image. It's just
    made of two update paths, both optionals:
    - minor, for updates available within the same release
    - major, for updates available in the next release

    An update file can be imported/exported as a dictionary:

      {
        'minor': { UPDATE_PATH },
        'major': { UPDATE_PATH },
      }

    -- This is the dataclass definition (requires python >= 3.7) --
    minor: UpdatePath
    major: UpdatePath
    """

    def __init__(self, minor, major):
        self.minor = minor
        self.major = major

    @classmethod
    def from_dict(cls, data):
        """Create an Update from a dictionary

        Raise exceptions if the dictionary doesn't contain the expected keys,
        or if values are not valid.
        """

        minor = {}
        if 'minor' in data:
            minor = UpdatePath.from_dict(data['minor'])

        major = {}
        if 'major' in data:
            major = UpdatePath.from_dict(data['major'])

        return cls(minor, major)

    def to_dict(self):
        """Export an Update to a dictionary"""

        data = {}
        if self.minor:
            data['minor'] = self.minor.to_dict()
        if self.major:
            data['major'] = self.major.to_dict()

        return data

    def to_string(self):
        """Export an Update to string"""

        data = self.to_dict()
        return json.dumps(data, indent=2)
