import os
import time


def test_plugins_load(qapp):
    import Purr.Plugins
    import Purr.Render
    assert Purr.Plugins.bad_plugins == {}
    assert {"fits", "image", "link"} <= set(Purr.Render.available_renderers)


def test_renderers_by_priority(qapp):
    import Purr.Render
    assert Purr.Render.getRenderers("x.fits")[0] == "fits"
    assert Purr.Render.getRenderers("x.png")[0] == "image"
    assert Purr.Render.getRenderers("x.unknown") == ["link"]


def _make_entry(purrer, workdir, title="First entry"):
    import Purr
    import Purr.Render
    files = [(str(workdir / "plot.png"), False), (str(workdir / "image.fits"), False)]
    dps = purrer.makeDataProducts(files, unbanish=True, unignore=True)
    assert [dp.filename for dp in dps] == ["image.fits", "plot.png"]
    for dp in dps:
        dp.render = Purr.Render.getRenderers(dp.sourcepath)[0]
    entry = Purr.LogEntry(time.time(), title, "A comment", dps)
    purrer.addLogEntry(entry)
    return entry


def test_log_roundtrip(qapp, tmp_path, workdir):
    import Purr

    logdir = tmp_path / "test.purrlog"
    purrer = Purr.Purrer(str(logdir), [str(workdir)])
    assert purrer.attached
    entry = _make_entry(purrer, workdir)

    # HTML index and icons for the log, and an entry directory with archived copies
    assert (logdir / "index.html").exists()
    assert (logdir / "purr16.png").exists()
    entry_dir = os.path.dirname(entry.index_file)
    assert os.path.exists(os.path.join(entry_dir, "image.fits"))
    assert os.path.exists(os.path.join(entry_dir, "plot.png"))
    index = (logdir / "index.html").read_text()
    assert "First entry" in index
    # the FITS renderer makes thumbnails/histograms in a subproduct directory
    entry_html = open(entry.index_file).read()
    assert "image.fits" in entry_html and "<IMG" in entry_html.upper()
    purrer.detach()

    # re-attaching loads the entry back from disk
    again = Purr.Purrer(str(logdir), [str(workdir)])
    entries = again.getLogEntries()
    assert [e.title for e in entries] == ["First entry"]
    assert sorted(dp.filename for dp in entries[0].dps) == ["image.fits", "plot.png"]
    again.detach()


def test_rescan_finds_new_files(qapp, tmp_path, workdir):
    import Purr

    purrer = Purr.Purrer(str(tmp_path / "scan.purrlog"), [str(workdir)])
    purrer.setWatchingState(str(workdir), Purr.POUNCE)
    purrer.rescan()  # initial scan
    newfile = workdir / "new.png"
    newfile.write_bytes((workdir / "plot.png").read_bytes())
    future = time.time() + 5
    # Purr spots new files via the directory mtime (with a 0.1s margin), so move both forward
    os.utime(newfile, (future, future))
    os.utime(workdir, (future, future))
    found = purrer.rescan()
    assert "new.png" in [dp.filename for dp in found]
    purrer.detach()


def test_disappeared_file_signal(qapp, tmp_path, workdir):
    import Purr

    purrer = Purr.Purrer(str(tmp_path / "gone.purrlog"), [str(workdir)])
    purrer.setWatchingState(str(workdir), Purr.POUNCE)
    purrer.rescan()
    gone = []
    purrer.disappearedFile.connect(gone.append)
    os.rename(workdir, workdir.with_name("moved"))
    purrer.rescan()
    assert str(workdir) in gone
    purrer.detach()
