import os

import pytest


@pytest.fixture
def mainwin(qapp, tmp_path, workdir, yes_to_dialogs):
    import Purr.MainWindow
    win = Purr.MainWindow.MainWindow(None)
    assert win.attachPurrlog(str(tmp_path / "gui.purrlog"), [str(workdir)])
    yield win
    win.detachPurrlog()
    win.close()


def test_add_entry_through_dialog(mainwin, workdir):
    dialog = mainwin.new_entry_dialog
    # "Add file..." in the dialog emits filesSelected(list); main window turns them into DPs
    dialog.filesSelected.emit([str(workdir / "plot.png"), str(workdir / "image.fits")])
    items = dialog.editor.wdplv.getItemDPList()
    assert sorted(dp.filename for item, dp in items) == ["image.fits", "plot.png"]

    added = []
    dialog.newLogEntry.connect(added.append)
    dialog.editor.setEntryTitle("GUI entry")
    dialog.addNewEntry()
    assert [e.title for e in added] == ["GUI entry"]
    assert mainwin.etw.topLevelItemCount() == 1
    assert os.path.exists(mainwin.purrer.indexfile)


def test_view_and_edit_entry(mainwin, workdir):
    dialog = mainwin.new_entry_dialog
    for title in ("one", "two"):
        dialog.filesSelected.emit([str(workdir / "plot.png")])
        dialog.editor.setEntryTitle(title)
        dialog.addNewEntry()
    assert mainwin.etw.topLevelItemCount() == 2

    viewer = mainwin.view_entry_dialog
    mainwin._viewEntryNumber(0)
    assert mainwin._viewing_ientry == 0
    viewer.showNext.emit()
    assert mainwin._viewing_ientry == 1
    viewer.showPrevious.emit()
    assert mainwin._viewing_ientry == 0

    # edit the entry title and save; entryChanged updates the main window
    changed = []
    viewer.entryChanged.connect(changed.append)
    viewer._editEntry()
    viewer.editor.setEntryTitle("renamed")
    viewer.editor.setUpdated()
    assert viewer.wsave.isEnabled()
    viewer._saveEntry()
    assert [e.title for e in changed] == ["renamed"]
    assert "renamed" in mainwin.etw.topLevelItem(0).text(1)


def test_regenerate_button(mainwin):
    calls = []
    mainwin.purrer.save = lambda refresh=False: calls.append(refresh)
    mainwin.viewer_dialog.buttonClicked.emit("Regenerate")
    assert calls == [True]
    mainwin.viewer_dialog.buttonClicked.emit("Something else")
    assert calls == [True]


def test_directory_list_signals(mainwin, workdir):
    import Purr
    wdirlist = mainwin.wdirlist
    assert wdirlist.count() == 1
    states = []
    wdirlist.directoryStateChanged.connect(lambda path, state: states.append((path, state)))
    item = wdirlist.item(0)
    # clicking the checkbox cycles UNWATCHED -> WATCHED -> POUNCE
    item.setCheckState(item.ToCheckState[Purr.POUNCE])
    assert states and states[-1][0] == str(workdir)
    assert mainwin.purrer.watchingState(str(workdir)) == states[-1][1]

    selected = []
    wdirlist.hasSelection.connect(selected.append)
    item.setSelected(True)
    assert selected[-1] is True


def test_drag_between_editors(mainwin, workdir):
    """Dropping files on one DP list removes them from the list they were dragged from."""
    dialog = mainwin.new_entry_dialog
    dialog.filesSelected.emit([str(workdir / "plot.png")])
    path = dialog.editor.wdplv.getItemDPList()[0][1].sourcepath
    dialog.editor.wdplv.draggedAwayFiles.emit([path])
    assert dialog.editor.wdplv.getItemDPList() == []


def test_startup_wizard_creates_log(qapp, tmp_path, workdir, yes_to_dialogs):
    import Purr.MainWindow
    import Purr.Startup
    from qtpy.QtWidgets import QDialog

    win = Purr.MainWindow.MainWindow(None)
    os.chdir(workdir)
    assert Purr.Startup.startWizard([str(workdir)], win, modal=False) is False
    wizard = Purr.Startup.wizard_dialog
    page = wizard._startpage
    assert page.rb_create.isChecked()
    assert page.isComplete()
    wizard.done(QDialog.Accepted)
    assert win.hasPurrlog()
    assert os.path.isdir(win.purrer.logdir)
    win.detachPurrlog()


def test_mouse_click_and_context_menus(mainwin, workdir, monkeypatch):
    """Real mouse events through Kittens.widgets.ClickableTreeWidget, and context menus."""
    from qtpy.QtTest import QTest
    from qtpy.QtCore import QPoint, Qt
    from qtpy.QtWidgets import QMenu

    shown_menus = []
    monkeypatch.setattr(QMenu, "exec", lambda self, *a: shown_menus.append(self))

    # new entry dialog: clicking the "comment" column of a DP opens an editor
    dialog = mainwin.new_entry_dialog
    dialog.show()
    dialog.filesSelected.emit([str(workdir / "plot.png")])
    tree = dialog.editor.wdplv
    item = tree.topLevelItem(0)
    rect = tree.visualItemRect(item)
    x = tree.header().sectionViewportPosition(tree.ColComment) + 5
    QTest.mouseClick(tree.viewport(), Qt.LeftButton, Qt.NoModifier, QPoint(x, rect.center().y()))
    assert tree._editing == (item, tree.ColComment)
    tree._startOrStopEditing()
    assert tree._editing is None

    # add an entry, then right-click it in the main window's log list
    dialog.editor.setEntryTitle("menu test")
    dialog.addNewEntry()
    etw = mainwin.etw
    entry_item = etw.topLevelItem(0)
    etw.customContextMenuRequested.emit(etw.visualItemRect(entry_item).center())
    assert shown_menus == [mainwin._entry_menu]
    assert mainwin._entry_menu_title.text() == '"menu test"'

    # right-click an archived data product under the entry
    etw.expandItem(entry_item)
    dp_item = entry_item.child(0)
    etw.customContextMenuRequested.emit(etw.visualItemRect(dp_item).center())
    assert shown_menus[-1] is mainwin._archived_dp_menu
    mainwin._copyItemToClipboard()
    from qtpy.QtWidgets import QApplication
    assert QApplication.clipboard().text().endswith("plot.png")
