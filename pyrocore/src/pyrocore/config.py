# -*- coding: utf-8 -*-
# pylint: disable-msg=I0011
""" PyroCore - Configuration.

    For details, see http://code.google.com/p/pyroscope/wiki/UserConfiguration

    Copyright (c) 2009, 2010 The PyroScope Project <pyrocore.project@gmail.com>

    This program is free software; you can redistribute it and/or modify
    it under the terms of the GNU General Public License as published by
    the Free Software Foundation; either version 2 of the License, or
    (at your option) any later version.

    This program is distributed in the hope that it will be useful,
    but WITHOUT ANY WARRANTY; without even the implied warranty of
    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
    GNU General Public License for more details.

    You should have received a copy of the GNU General Public License along
    with this program; if not, write to the Free Software Foundation, Inc.,
    51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.
"""
from pyrocore.util.types import Bunch


def lookup_announce_alias(name):
    """ Get canonical alias name and announce URL list for the given alias.
    """
    for alias, urls in announce.items():
        if alias.lower() == name.lower():
            return alias, urls

    raise KeyError("Unknown alias %s" % (name,))


# Remember predefined names
_PREDEFINED = tuple(_ for _ in globals() if not _.startswith('_'))

# Set some defaults to shut up pydev / pylint
scgi_local = ""
engine = Bunch(open=lambda: None)
output_format = ""
announce = {}
