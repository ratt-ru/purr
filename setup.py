#!/usr/bin/env python

from setuptools import setup, find_packages


data_files = [
    ('share/purr/icons', [
        'Purr/icons/blue_round_reload.png',
        'Purr/icons/filesave.png',
        'Purr/icons/editdelete.png',
        'Purr/icons/move.png',
        'Purr/icons/filefind.png',
        'Purr/icons/editclear.png',
        'Purr/icons/checkmark.png',
        'Purr/icons/list_remove.png',
        'Purr/icons/magnifying_glass.png',
        'Purr/icons/filenew.png',
        'Purr/icons/folder_open.png',
        'Purr/icons/list_add.png',
        'Purr/icons/grey_round_cross.png',
        'Purr/icons/edit.png',
        'Purr/icons/next.png',
        'Purr/icons/editcopy.png',
        'Purr/icons/openbook.png',
        'Purr/icons/editpaste.png',
        'Purr/icons/previous.png',
        'Purr/icons/purr_logo.xpm',
        'Purr/icons/red_round_cross.png',
        'Purr/icons/copy.png',
    ])]

setup(name='purr',
      version='1.3.0',
      description='Data reduction logging tool, Useful for remembering reductions',
      author='Oleg Smirnov',
      author_email='Oleg Smirnov <osmirnov@gmail.com>',
      url='https://github.com/ska-sa/purr',
      packages=find_packages(),
      requires=['kittens', 'PyQt4', 'pillow', 'scipy'],
      scripts=['Purr/purr.py', 'Purr/purr'],
      data_files=data_files,
      setup_requires=['pytest-runner'],
      tests_require=['pytest'],
      test_suite="tests",
      license="GPL2",
      classifiers=[
          "Development Status :: 5 - Production/Stable",
          "License :: OSI Approved :: GNU General Public License v2 (GPLv2)",
          "Programming Language :: Python",
          "Programming Language :: Python :: 2",
          "Programming Language :: Python :: 2.7",
          "Programming Language :: Python :: 3",
          "Programming Language :: Python :: 3.4",
          "Programming Language :: Python :: 3.5",
          "Programming Language :: Python :: 3.6",
          "Programming Language :: Python :: 3.7",
          "Environment :: X11 Applications",
      ]
     )
