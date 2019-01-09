# -*- coding: utf-8 -*-
Version = "1.1"

# some global constants

# these are the different watching modes for the directories
REMOVED = -1;  # directory removed from watchlist
UNWATCHED = 0;  # directory in list, but not watched
WATCHED = 1;  # directory watched for new files quietly
POUNCE = 2;  # directory watched loudly

import os.path

# init debug printing
import Kittens.utils

verbosity = Kittens.utils.verbosity(name="purr")
dprint = verbosity.dprint
dprintf = verbosity.dprintf

import Kittens.pixmaps

pixmaps = Kittens.pixmaps.PixmapCache("Purr")

import Kittens.config

ConfigFile = Kittens.config.DualConfigParser("purr.conf")
Config = Kittens.config.SectionParser(ConfigFile, "Purr")

from .LogEntry import DataProduct, LogEntry
from .Purrer import Purrer
from . import Parsers


# if GUI is enabled, this will be overwritten by an object that
# sets a busy cursor on instantiation, and restores the cursor when killed
class BusyIndicator(object):
    pass


def canonizePath(path):
    """Returns the absolute, normalized, real path  of something.
    This takes care of symbolic links, redundant separators, etc."""
    return os.path.abspath(os.path.normpath(os.path.realpath(path)))


def progressMessage(msg, sub=False):
    """shows a progress message. If a GUI is available, this will be redefined by the GUI.
    If sub is true, message is a sub-message of previous one."""
    pass
