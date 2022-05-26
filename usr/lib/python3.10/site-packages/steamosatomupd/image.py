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

import datetime
import platform
import re
import semantic_version

def _load_os_release():
    """Load /etc/os-release in a dictionary"""

    envre = re.compile(r'''^([^\s=]+)=(?:[\s"']*)(.+?)(?:[\s"']*)$''')
    data = {}

    with open('/etc/os-release') as f:
        for line in f:
            match = envre.match(line)
            if match is not None:
                data[match.group(1)] = match.group(2)

    return data

class BuildId:

    """A build ID"""

    def __init__(self, date, increment):
        self.date = date
        self.incr = increment

    @classmethod
    def from_string(cls, text):
        """Create a BuildId from a string containing the date and the increment.

        The date is expected to be ISO-8601, basic format. The increment is separated
        from the date by a dot, and is optional. It's set to zero if missing.

        Examples: 20181105, 20190211.1
        """

        date = None
        incr = 0

        fields = text.split('.')

        if len(fields) > 2:
            raise ValueError("the version string should match YYYYMMDD[.N]")
        if len(fields) > 1:
            incr = int(fields[1])
            if incr < 0:
                raise ValueError("the increment should be positive")
        # Parse date, raise ValueError if need be
        date = datetime.datetime.strptime(fields[0], '%Y%m%d').date()

        return cls(date, incr)

    def __eq__(self, other):
        return ((self.date, self.incr) == (other.date, other.incr))

    def __ne__(self, other):
        return not (self == other)

    def __lt__(self, other):
        return ((self.date, self.incr) <  (other.date, other.incr))

    def __le__(self, other):
        return ((self.date, self.incr) <= (other.date, other.incr))

    def __gt__(self, other):
        return ((self.date, self.incr) >  (other.date, other.incr))

    def __ge__(self, other):
        return ((self.date, self.incr) >= (other.date, other.incr))

    def __repr__(self):
        return "{}.{}".format(self.date.strftime('%Y%m%d'), self.incr)

    def __str__(self):
        return self.__repr__()


class Image:

    """An OS image

    -- This is the dataclass definition (requires python >= 3.7) --
    product: str
    release: str
    variant: str
    arch: str
    version: SemanticVersion
    buildid: BuildId
    checkpoint: bool
    estimated_size: int
    """

    def __init__(self, product, release, variant, arch, version, buildid,
                 checkpoint, estimated_size):
        self.product = product
        self.release = release
        self.variant = variant
        self.arch = arch
        self.version = version
        self.buildid = buildid
        self.checkpoint = checkpoint
        self.estimated_size = estimated_size

    @classmethod
    def from_values(cls, product, release, variant, arch,
                    version_str, buildid_str, checkpoint, estimated_size):
        """Create an Image from mandatory values

        This method performs mandatory conversions and sanity checks before
        feeding the values to the constructor. Every other classmethod
        constructors should call it.
        """

        # Parse version, raise ValueError if need be
        if version_str == 'snapshot':
            version = None
        else:
            # https://github.com/rbarrois/python-semanticversion/issues/29
            version = semantic_version.Version.coerce(version_str)

        # Parse buildid, raise ValueError if need be
        buildid = BuildId.from_string(buildid_str)

        # Tweak architecture a bit
        if arch == 'x86_64':
            arch = 'amd64'

        # Return an instance
        return cls(product, release, variant, arch, version, buildid, checkpoint, estimated_size)

    @classmethod
    def from_dict(cls, data):
        """Create an Image from a dictionary.

        Raise exceptions if the dictionary doesn't contain the expected keys,
        or if values are not valid.
        """

        # Get mandatory fields, raise KeyError if need be
        product = data['product']
        release = data['release']
        variant = data['variant']
        arch    = data['arch']
        version_str = data['version']
        buildid_str = data['buildid']

        # Get optional fields
        checkpoint = False
        if 'checkpoint' in data:
            checkpoint = data['checkpoint']

        estimated_size = data.get('estimated_size', 0)

        # Return an instance
        return cls.from_values(product, release, variant, arch,
                               version_str, buildid_str, checkpoint,
                               estimated_size)

    @classmethod
    def from_os(cls, product=None, release=None, variant=None, arch=None,
                version_str=None, buildid_str=None, checkpoint=False,
                estimated_size=0):
        """Create an Image with parameters, use running OS for defaults.

        All arguments are optional, and default values are taken by inspecting the
        current system. The os-release file provides for most of the default values.

        'checkpoint' does not exist in any standard place, hence it's assumed to be
        false if it's not provided. Note that os-release allows custom additional
        fields (and recommends to use some kind of namespacing), so we could look for
        'checkpoint' in a custom field named ${PRODUCT}_CHECKPOINT, for example.

        If a value is not specified and can't be found in the os-release, we raise
        a RuntimeError exception.
        """

        # Load the os-release file
        osrel = _load_os_release()

        # All these parameters are mandatory. If they're not specified, they
        # must have a default value in the os-release file.
        try:
            if not product:
                product = osrel['ID']
            if not release:
                release = osrel['VERSION_CODENAME']
            if not variant:
                variant = osrel['VARIANT_ID']
            if not version_str:
                version_str = osrel['VERSION_ID']
            if not buildid_str:
                buildid_str = osrel['BUILD_ID']
        except KeyError as e:
            raise RuntimeError("Missing key in os-release: {}".format(e))

        # Arch comes from the platform
        if not arch:
            arch = platform.machine()

        # Return an instance, might raise exceptions
        return cls.from_values(product, release, variant, arch,
                               version_str, buildid_str, checkpoint,
                               estimated_size)

    def to_dict(self):
        """Export an Image to a dictionary"""

        data = {}

        data['product'] = self.product
        data['release'] = self.release
        data['variant'] = self.variant
        data['arch'] = self.arch
        if self.version:
            data['version'] = str(self.version)
        else:
            data['version'] = 'snapshot'
        data['buildid'] = str(self.buildid)
        data['checkpoint'] = self.checkpoint
        data['estimated_size'] = self.estimated_size

        return data

    def is_snapshot(self):
        """Whether an Image is a snapshot"""

        return not self.version

    def is_stable(self):
        """Whether an Image is stable (ie. it has a stable version)"""

        if self.version:
            return not self.version.prerelease
        else:
            return False

    # A note regarding comparison operators.
    #
    # When comparing images, we care about version OR (release, buildid).
    #
    # When versions are defined for both images, we just compare it.
    #
    # When there is no version for both images, we compare releases first,
    # then build IDs. We expect releases to be strings such as 'brewmaster',
    # 'clockwerk' and so on, sorted alphabetically. It means that when we
    # compare 'brewmaster 20190201' and 'clockwerk 20180201', clockwerk is
    # higher.
    #
    # If ever we have to compare an image with a version against an image
    # without, we raise an exception. These two can't be compared. Note that
    # such comparison shouldn't happen anyway, the calling code should take
    # care of never letting this situation happen.

    def __eq__(self, other):
        if self.version and other.version:
            return (self.version == other.version)
        if not self.version and not other.version:
            return ((self.release, self.buildid) == (other.release, other.buildid))
        raise RuntimeError("Can't compare snapshot with versioned image")

    def __ne__(self, other):
        return not (self == other)

    def __lt__(self, other):
        if self.version and other.version:
            return (self.version < other.version)
        if not self.version and not other.version:
            return ((self.release, self.buildid) < (other.release, other.buildid))
        raise RuntimeError("Can't compare snapshot with versioned image")

    def __le__(self, other):
        if self.version and other.version:
            return (self.version <= other.version)
        if not self.version and not other.version:
            return ((self.release, self.buildid) <= (other.release, other.buildid))
        raise RuntimeError("Can't compare snapshot with versioned image")

    def __gt__(self, other):
        if self.version and other.version:
            return (self.version > other.version)
        if not self.version and not other.version:
            return ((self.release, self.buildid) > (other.release, other.buildid))
        raise RuntimeError("Can't compare snapshot with versioned image")

    def __ge__(self, other):
        if self.version and other.version:
            return (self.version >= other.version)
        if not self.version and not other.version:
            return ((self.release, self.buildid) >= (other.release, other.buildid))
        raise RuntimeError("Can't compare snapshot with versioned image")

    def __repr__(self):
        return "{{ {}, {}, {}, {}, {}, {}, {} }}".format(
            self.product, self.release, self.variant, self.arch,
            self.version, self.buildid, self.checkpoint)
