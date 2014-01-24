#!/usr/bin/env python

from distutils.core import setup

setup(name='purr',
      version='1.3.0',
      description='Data reduction logging tool, Useful for remembering reductions',
      author='Oleg Smirnov',
      author_email='Oleg Smirnov <osmirnov@gmail.com>',
      url='https://github.com/ska-sa/purr',
      packages=['Purr'],
      requires=['kittens'],
      scripts=['Purr/purr.py', 'Purr/purr'],
     )
