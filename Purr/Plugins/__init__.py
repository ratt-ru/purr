# -*- coding: utf-8 -*-
import fnmatch
import importlib.util
import os
import os.path
import sys
import traceback

import Purr
import Purr.Render
from Purr import dprintf


def loadPlugins(paths):
    global bad_plugins
    bad_plugins = {}
    # find potential plugin files
    modfiles = set()
    for path in paths:
        files = set(fnmatch.filter(os.listdir(path), "*.py"))
        files.discard('__init__.py')
        modfiles.update([os.path.join(path, file) for file in files])
    dprintf(1, "%d plugins found\n", len(modfiles))
    # try to import them
    for fullpath in modfiles:
        modfile = os.path.basename(fullpath)
        modname, ext = os.path.splitext(modfile)
        pathname = fullpath
        fullname = 'Purr.Plugins.%s' % modname
        # try to import the module
        try:
            spec = importlib.util.spec_from_file_location(fullname, pathname)
            module = importlib.util.module_from_spec(spec)
            sys.modules[fullname] = module
            try:
                spec.loader.exec_module(module)
            except BaseException:
                del sys.modules[fullname]
                raise
        except Exception:
            err = sys.exc_info()[1]
            dprintf(0, "Error importing module %s: %s\n", pathname, err)
            traceback.print_exc()
            bad_plugins[modname] = err
            continue
        # ok, we have a module, check for vital properties
        dprintf(1, "Imported plugin module '%s' from %s\n", modname, pathname)
    dprintf(1, "%d renderers now available\n", Purr.Render.numRenderers())


# this collects a list of plugins that have failed to load
bad_plugins = None

if bad_plugins is None:
    loadPlugins(__path__)  # type: ignore  # mypy issue #1422
