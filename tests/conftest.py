import os
import tempfile

# Run Qt headless, and keep Purr's config file (~/.purrrc) out of the real home
# directory. Both must be set before Purr or Qt are imported.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["HOME"] = tempfile.mkdtemp(prefix="purr-test-home-")

import numpy
import pytest


@pytest.fixture(scope="session")
def qapp():
    from qtpy.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def workdir(tmp_path):
    """A directory containing a PNG and a FITS image, like a data reduction directory."""
    import PIL.Image
    from astropy.io import fits

    work = tmp_path / "work"
    work.mkdir()
    PIL.Image.new("RGB", (64, 48), (200, 30, 30)).save(work / "plot.png")
    data = numpy.random.default_rng(1).normal(size=(32, 32)).astype("float32")
    fits.PrimaryHDU(data).writeto(work / "image.fits")
    return work


@pytest.fixture
def yes_to_dialogs(monkeypatch):
    """Answer Yes to every QMessageBox question/warning instead of blocking."""
    from qtpy.QtWidgets import QMessageBox
    for name in ("question", "warning", "information"):
        monkeypatch.setattr(QMessageBox, name, staticmethod(lambda *a, **kw: QMessageBox.Yes))
