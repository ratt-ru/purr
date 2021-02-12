#!/usr/bin/env python

import os
from distutils.core import setup
from distutils.command.install import INSTALL_SCHEMES

data_files = []
root_dir = os.path.dirname(__file__)
if root_dir != '':
    os.chdir(root_dir)

# collect a list of all non python files
for dirpath, dirnames, filenames in os.walk('Purr'):
    dirnames[:] = [d for d in dirnames if not d.startswith('.') and d != '__pycache__']
    if filenames and '__init__.py' not in filenames:
        data_files.append([dirpath, [os.path.join(dirpath, f) for f in filenames]])

# Tell distutils not to put the data_files in platform-specific installation
# locations. See here for an explanation:
# http://groups.google.com/group/comp.lang.python/browse_thread/thread/35ec7b2fed36eaec/2105ee4d9e8042cb
for scheme in list(INSTALL_SCHEMES.values()):
        scheme['data'] = scheme['purelib']

setup(name='purr',
      version='1.5.1',
      description='Data reduction logging tool, Useful for remembering reductions',
      author='Oleg Smirnov',
      author_email='Oleg Smirnov <osmirnov@gmail.com>',
      url='https://github.com/ska-sa/purr',
      packages=['Purr', 'Purr/Plugins', 'Purr/Plugins/local_pychart', 'Purr/Plugins/local_pychart/afm'],
      install_requires=['kittens', 'pillow', 'scipy', 'astropy', 'future'],  # 'PyQt4',
      scripts=['Purr/purr.py', 'Purr/purr'],
      data_files=data_files,
     )
