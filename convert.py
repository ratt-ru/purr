import os


template = \
"""
from {path} import {script}
from unittest import TestCase


class Test{script}(TestCase):
    def test_{script}(self):
        pass

"""

for root, dirs, files in os.walk("Purr"):
    for file in (f for f in files if f.endswith('.py')):
        module = "test_" + file.lower()
        path = root.replace("/", ".")
        print(root, file, module)
        with open('tests/' + module, 'w') as f:
            f.write(template.format(path=path, script=file[:-3]))


