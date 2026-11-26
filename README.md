purr
====

Data reduction logging tool, Useful for remembering reductions.

Purr needs Python 3.10–3.14 and a Qt binding (PyQt5 or PyQt6, used through
[qtpy](https://github.com/spyder-ide/qtpy)).

On KERN/Ubuntu/Debian, get Qt from apt and install Purr on top:

```shell
 $ sudo apt install python3-pyqt5 python3-qtpy
 $ pip install .
```

Or install everything with pip:

```shell
 $ pip install ".[pyqt5]"     # or ".[pyqt6]"
```

To choose a binding when several are installed, set `QT_API=pyqt5` or `QT_API=pyqt6`.

Then run `purr <directory to watch>`.

Running the tests:

```shell
 $ pip install ".[test]"
 $ QT_QPA_PLATFORM=offscreen pytest
```
