# -*- coding: utf-8 -*-
_tdl_no_reimport = True

import os.path
import time

import Kittens.utils
import Kittens.widgets
from PyQt4.Qt import (QWidget, QDialog, QWizard, QWizardPage, QButtonGroup, QVBoxLayout,
                      QRadioButton, QObject, SIGNAL, QHBoxLayout, QLineEdit, QPushButton,
                      QFileDialog, QMessageBox, QHeaderView, QAbstractItemView,
                      QFontMetrics, QFont, QTreeWidget, QSizePolicy, QMenu, QMimeData, QUrl,
                      QComboBox, QMimeData, QTreeWidgetItem, Qt, QApplication,
                      QClipboard, QLabel, QSplitter, QTextEdit, QTextDocument, QSize,
                      QFrame, QStackedWidget, QWidgetAction, QMenu, QTextBrowser, QPoint,
                      QDrag, QListWidget, QListWidgetItem, QMainWindow, QToolBar, QTimer,
                      QCoreApplication, QEventLoop, QCursor, QListWidget)
import six
if six.PY3:
    QVariant = str
else:
    from PyQt4.Qt import (QVariant)

import Purr
import Purr.Editors
import Purr.LogEntry
import Purr.Pipe
import Purr.RenderIndex
from Purr import Config, pixmaps, dprint


class BusyIndicator(object):
    def __init__(self):
        QApplication.setOverrideCursor(QCursor(Qt.WaitCursor))

    def __del__(self):
        QApplication.restoreOverrideCursor()


class HTMLViewerDialog(QDialog):
    """This class implements a dialog to view a piece of HTML text."""

    def __init__(self, parent, config_name=None, buttons=[], *args):
        """Creates dialog.
        'config_name' is used to get/set default window size from Config object
        'buttons' can be a list of names or (QPixmapWrapper,name[,tooltip]) tuples to provide
        custom buttons at the bottom of the dialog. When a button is clicked, the dialog
        emits SIGNAL("name").
        A "Close" button is always provided, this simply hides the dialog.
        """
        QDialog.__init__(self, parent, *args)
        self.setModal(False)
        lo = QVBoxLayout(self)
        # create viewer
        self.label = QLabel(self)
        self.label.setMargin(5)
        self.label.setWordWrap(True)
        lo.addWidget(self.label)
        self.label.hide()
        self.viewer = QTextBrowser(self)
        lo.addWidget(self.viewer)
        # self.viewer.setReadOnly(True)
        self.viewer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        QObject.connect(self.viewer, SIGNAL("anchorClicked(const QUrl &)"), self._urlClicked)
        self._source = None
        lo.addSpacing(5)
        # create button bar
        btnfr = QFrame(self)
        btnfr.setSizePolicy(QSizePolicy.MinimumExpanding, QSizePolicy.Fixed)
        # btnfr.setMargin(5)
        lo.addWidget(btnfr)
        lo.addSpacing(5)
        btnfr_lo = QHBoxLayout(btnfr)
        btnfr_lo.setMargin(5)
        # add user buttons
        self._user_buttons = {}
        for name in buttons:
            if isinstance(name, str):
                btn = QPushButton(name, btnfr)
            elif isinstance(name, (list, tuple)):
                if len(name) < 3:
                    pixmap, name = name
                    tip = None
                else:
                    pixmap, name, tip = name
                btn = QPushButton(pixmap.icon(), name, btnfr)
                if tip:
                    btn.setToolTip(tip)
            self._user_buttons[name] = btn
            btn._clicked = Kittens.utils.curry(self.emit, SIGNAL(name))
            self.connect(btn, SIGNAL("clicked()"), btn._clicked)
            btnfr_lo.addWidget(btn, 1)
        # add a Close button
        btnfr_lo.addStretch(100)
        closebtn = QPushButton(pixmaps.grey_round_cross.icon(), "Close", btnfr)
        self.connect(closebtn, SIGNAL("clicked()"), self.hide)
        btnfr_lo.addWidget(closebtn, 1)
        # resize selves
        self.config_name = config_name or "html-viewer"
        width = Config.getint('%s-width' % self.config_name, 512)
        height = Config.getint('%s-height' % self.config_name, 512)
        self.resize(QSize(width, height))

    def resizeEvent(self, ev):
        QDialog.resizeEvent(self, ev)
        sz = ev.size()
        Config.set('%s-width' % self.config_name, sz.width())
        Config.set('%s-height' % self.config_name, sz.height())

    def setDocument(self, filename, empty=""):
        """Sets the HTML text to be displayed. """
        self._source = QUrl.fromLocalFile(filename)
        if os.path.exists(filename):
            self.viewer.setSource(self._source)
        else:
            self.viewer.setText(empty)

    def _urlClicked(self, url):
        path = str(url.path())
        if path:
            self.emit(SIGNAL("viewPath"), path)
        # to make sure it keeps displaying the same thing
        self.viewer.setSource(self._source)

    def reload(self):
        self.viewer.reload()

    def setLabel(self, label=None):
        if label is None:
            self.label.hide()
        else:
            self.label.setText(label)
            self.label.show()

            # self.watching = bool(enable)
            # if enable:
            #  self.purrer.enableWatching(self.path)
            # else:
            #  self.purrer.disableWatching(self.path)
            # self.mainwin._checkPounceStatus()


class DirectoryListWidget(Kittens.widgets.ClickableListWidget):
    """This class implements a QTreeWidget for data products.
    """

    def __init__(self, *args):
        Kittens.widgets.ClickableListWidget.__init__(self, *args)
        # insert columns, and numbers for them
        # setup other properties of the listview
        self.setAcceptDrops(True)
        self.setSelectionMode(QListWidget.SingleSelection)
        self.setSizePolicy(QSizePolicy.MinimumExpanding, QSizePolicy.Minimum)
        QObject.connect(self, SIGNAL("itemSelectionChanged()"), self._selectionChanged)
        QObject.connect(self, SIGNAL("itemChanged(QListWidgetItem *)"), self._itemChanged)
        self._items = {}
        self._item_height = None
        self._max_height_items = 5
        self._min_height = 8
        self.setMaximumSize(1000000, self._min_height)

    class DirItem(QListWidgetItem):
        # these represent the watch-states
        ToCheckState = {Purr.UNWATCHED: Qt.Unchecked, Purr.WATCHED: Qt.PartiallyChecked, Purr.POUNCE: Qt.Checked}
        FromCheckState = dict([(state, watch) for watch, state in list(ToCheckState.items())])

        def __init__(self, pathname, parent=None, watching=Purr.WATCHED):
            self._pathname = pathname
            pathname = Kittens.utils.collapseuser(pathname)
            self._in_setWatching = True
            QListWidgetItem.__init__(self, pathname, parent)
            self.setFlags(Qt.ItemIsSelectable | Qt.ItemIsUserCheckable | Qt.ItemIsEnabled | Qt.ItemIsTristate)
            self.setWatching(watching)

        def pathname(self):
            return self._pathname

        def watching(self):
            return self.FromCheckState[self.checkState()]

        def setWatching(self, watching):
            self._in_setWatching = True
            self._watching = watching
            self.setCheckState(self.ToCheckState[watching])
            self._in_setWatching = False

    def _selectionChanged(self):
        sel = self.selectedItems()
        self.emit(SIGNAL("directorySelected"), sel and sel[0].pathname())
        self.emit(SIGNAL("hasSelection"), bool(sel))

    def _itemChanged(self, item):
        if not getattr(item, '_in_setWatching', False):
            item.setWatching((item._watching + 1) % (Purr.POUNCE + 1))
            self.emit(SIGNAL("directoryStateChanged"), item.pathname(), item.watching())

    def _checkSize(self):
        """Automatically resizes widget to display at most max_height_items items"""
        if self._item_height is not None:
            sz = min(self._max_height_items, self.count()) * self._item_height + 5
            sz = max(sz, 20)
            self.setMinimumSize(0, sz)
            self.setMaximumSize(1000000, sz)
            self.resize(self.width(), sz)

    def clear(self):
        Kittens.widgets.ClickableListWidget.clear(self)
        self._items = {}

    def add(self, pathname, watching=Purr.WATCHED):
        if pathname in self._items:
            return
        item = self._items[pathname] = self.DirItem(pathname, parent=self, watching=watching)
        # init item height, if inserting first item
        if self._item_height is None:
            self._item_height = self.visualItemRect(item).height()
        self._checkSize()

    def remove(self, pathname):
        item = self._items.get(pathname, None)
        return item and self._removeItem(item)

    def _removeItem(self, item):
        del self._items[item.pathname()]
        self.emit(SIGNAL("directoryStateChanged"), item.pathname(), Purr.REMOVED)
        self.takeItem(self.row(item))
        self._checkSize()

    def removeCurrent(self, confirm=True):
        sel = self.selectedItems()
        if sel:
            if confirm:
                if QMessageBox.warning(self, "Detaching from directory",
                                       """Do you really want to stop monitoring the directory <tt>%s</tt>?""" % sel[
                                           0].pathname(),
                                       QMessageBox.Yes, QMessageBox.No) == QMessageBox.Yes:
                    return self._removeItem(sel[0])
        return None


class LogEntryTree(Kittens.widgets.ClickableTreeWidget):
    def __init__(self, *args):
        Kittens.widgets.ClickableTreeWidget.__init__(self, *args)
        self.setDragEnabled(True)

    def mimeTypes(self):
        return ["text/x-url"]

    def mimeData(self, itemlist):
        mimedata = QMimeData()
        urls = []
        for item in itemlist:
            dp = getattr(item, "_dp", None)
            dp and urls.append(QUrl.fromLocalFile(dp.fullpath or dp.sourcepath))
        mimedata.setUrls(urls)
        return mimedata


class MainWindow(QMainWindow):
    about_message = """
    <P>PURR ("<B>P</B>URR is <B>U</B>seful for <B>R</B>emembering <B>R</B>eductions", for those working with
    a stable version, or "<B>P</B>URR <B>U</B>sually <B>R</B>emembers <B>R</B>eductions", for those
    working with a development version, or "<B>P</B>URR <B>U</B>sed to <B>R</B>emember <B>R</B>eductions",
    for those working with a broken version) is a tool for
    automatically keeping a log of your data reduction operations. PURR will monitor your working directories
    for new or updated files (called "data products"), and upon seeing any, it can "pounce" -- that is, offer
    you the option of saving the files to a log, along with descriptive comments. It will then
    generate an HTML page with a pretty rendering of your log and data products.</P>
  """

    def __init__(self, parent, hide_on_close=False):
        QMainWindow.__init__(self, parent)
        self._hide_on_close = hide_on_close
        # replace the BusyIndicator class with a GUI-aware one
        Purr.BusyIndicator = BusyIndicator
        self._pounce = False
        # we keep a small stack of previously active purrers. This makes directory changes
        # faster (when going back and forth between dirs)
        # current purrer
        self.purrer = None
        self.purrer_stack = []
        # Purr pipes for receiving remote commands
        self.purrpipes = {}
        # init GUI
        self.setWindowTitle("PURR")
        self.setWindowIcon(pixmaps.purr_logo.icon())
        cw = QWidget(self)
        self.setCentralWidget(cw)
        cwlo = QVBoxLayout(cw)
        cwlo.setContentsMargins(0, 0, 0, 0)
        cwlo.setMargin(5)
        cwlo.setSpacing(0)
        toplo = QHBoxLayout();
        cwlo.addLayout(toplo)

        # About dialog
        self._about_dialog = QMessageBox(self)
        self._about_dialog.setWindowTitle("About PURR")
        self._about_dialog.setText(self.about_message + """
        <P>PURR is not watching any directories right now. You may need to restart it, and give it
  some directory names on the command line.</P>""")
        self._about_dialog.setIconPixmap(pixmaps.purr_logo.pm())
        # Log viewer dialog
        self.viewer_dialog = HTMLViewerDialog(self, config_name="log-viewer",
                                              buttons=[(pixmaps.blue_round_reload, "Regenerate",
                                                        """<P>Regenerates your log's HTML code from scratch. This can be useful if
                                                        your PURR version has changed, or if there was an error of some kind
                                                        the last time the files were generated.</P>
                                                        """)])
        self._viewer_timestamp = None
        self.connect(self.viewer_dialog, SIGNAL("Regenerate"), self._regenerateLog)
        self.connect(self.viewer_dialog, SIGNAL("viewPath"), self._viewPath)

        # Log title toolbar
        title_tb = QToolBar(cw)
        title_tb.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        title_tb.setIconSize(QSize(16, 16))
        cwlo.addWidget(title_tb)
        title_label = QLabel("Purrlog title:", title_tb)
        title_tb.addWidget(title_label)
        self.title_editor = QLineEdit(title_tb)
        title_tb.addWidget(self.title_editor)
        self.connect(self.title_editor, SIGNAL("editingFinished()"), self._titleChanged)
        tip = """<P>This is your current log title. To rename the log, enter new name here and press Enter.</P>"""
        title_label.setToolTip(tip)
        self.title_editor.setToolTip(tip)
        self.wviewlog = title_tb.addAction(pixmaps.openbook.icon(), "View", self._showViewerDialog)
        self.wviewlog.setToolTip("Click to see an HTML rendering of your current log.")
        qa = title_tb.addAction(pixmaps.purr_logo.icon(), "About...", self._about_dialog.exec_)
        qa.setToolTip("<P>Click to see the About... dialog, which will tell you something about PURR.</P>")

        self.wdirframe = QFrame(cw)
        cwlo.addWidget(self.wdirframe)
        self.dirs_lo = QVBoxLayout(self.wdirframe)
        self.dirs_lo.setMargin(5)
        self.dirs_lo.setContentsMargins(5, 0, 5, 5)
        self.dirs_lo.setSpacing(0)
        self.wdirframe.setFrameStyle(QFrame.Box | QFrame.Raised)
        self.wdirframe.setLineWidth(1)

        ## Directories toolbar
        dirs_tb = QToolBar(self.wdirframe)
        dirs_tb.setToolButtonStyle(Qt.ToolButtonIconOnly)
        dirs_tb.setIconSize(QSize(16, 16))
        self.dirs_lo.addWidget(dirs_tb)
        label = QLabel("Monitoring directories:", dirs_tb)
        self._dirs_tip = """<P>PURR can monitor your working directories for new or updated files. If there's a checkmark
      next to the directory name in this list, PURR is monitoring it.</P>

      <P>If the checkmark is grey, PURR is monitoring things unobtrusively. When a new or updated file is detected in he monitored directory,
      it is quietly added to the list of files in the "New entry" window, even if this window is not currently visible.</P>

      <P>If the checkmark is black, PURR will be more obtrusive. Whenever a new or updated file is detected, the "New entry" window will
      pop up automatically. This is called "pouncing", and some people find it annoying.</P>
      """
        label.setToolTip(self._dirs_tip)
        label.setSizePolicy(QSizePolicy.MinimumExpanding, QSizePolicy.Minimum)
        dirs_tb.addWidget(label)

        # add directory list widget
        self.wdirlist = DirectoryListWidget(self.wdirframe)
        self.wdirlist.setToolTip(self._dirs_tip)
        QObject.connect(self.wdirlist, SIGNAL("directoryStateChanged"), self._changeWatchedDirState)
        self.dirs_lo.addWidget(self.wdirlist)
        # self.wdirlist.setMaximumSize(1000000,64)

        # add directory button
        add = dirs_tb.addAction(pixmaps.list_add.icon(), "Add", self._showAddDirectoryDialog)
        add.setToolTip("<P>Click to add another directory to be monitored.</P>")

        # remove directory button
        delbtn = dirs_tb.addAction(pixmaps.list_remove.icon(), "Remove", self.wdirlist.removeCurrent)
        delbtn.setEnabled(False)
        delbtn.setToolTip("<P>Click to removed the currently selected directory from the list.</P>")
        QObject.connect(self.wdirlist, SIGNAL("hasSelection"), delbtn.setEnabled)

        #    # qa = dirs_tb.addAction(pixmaps.blue_round_reload.icon(),"Rescan",self._forceRescan)
        #    # qa.setToolTip("Click to rescan the directories for any new or updated files.")
        #    self.wshownew = QCheckBox("show new files",dirs_tb)
        #    dirs_tb.addWidget(self.wshownew)
        #    self.wshownew.setCheckState(Qt.Checked)
        #    self.wshownew.setToolTip("""<P>If this is checked, the "New entry" window will pop up automatically whenever
        #  new or updated files are detected. If this is unchecked, the files will be added to the window quietly
        #        and unobtrusively; you can show the window manually by clicking on the "New entry..." button below.</P>""")
        #    self._dir_entries = {}

        cwlo.addSpacing(5)

        wlogframe = QFrame(cw)
        cwlo.addWidget(wlogframe)
        log_lo = QVBoxLayout(wlogframe)
        log_lo.setMargin(5)
        log_lo.setContentsMargins(5, 5, 5, 5)
        log_lo.setSpacing(0)
        wlogframe.setFrameStyle(QFrame.Box | QFrame.Raised)
        wlogframe.setLineWidth(1)

        # listview of log entries
        self.etw = LogEntryTree(cw)
        log_lo.addWidget(self.etw, 1)
        self.etw.header().setDefaultSectionSize(128)
        self.etw.header().setMovable(False)
        self.etw.setHeaderLabels(["date", "entry title", "comment"])
        if hasattr(QHeaderView, 'ResizeToContents'):
            self.etw.header().setResizeMode(0, QHeaderView.ResizeToContents)
        else:
            self.etw.header().setResizeMode(0, QHeaderView.Custom)
            self.etw.header().resizeSection(0, 120)
        self.etw.header().setResizeMode(1, QHeaderView.Interactive)
        self.etw.header().setResizeMode(2, QHeaderView.Stretch)
        self.etw.header().show()
        try:
            self.etw.setAllColumnsShowFocus(True)
        except AttributeError:
            pass;  # Qt 4.2+
        # self.etw.setShowToolTips(True)
        self.etw.setSortingEnabled(False)
        # self.etw.setColumnAlignment(2,Qt.AlignLeft|Qt.AlignTop)
        self.etw.setSelectionMode(QTreeWidget.ExtendedSelection)
        self.etw.setRootIsDecorated(True)
        self.connect(self.etw, SIGNAL("itemSelectionChanged()"), self._entrySelectionChanged)
        self.connect(self.etw, SIGNAL("itemActivated(QTreeWidgetItem*,int)"), self._viewEntryItem)
        self.connect(self.etw, SIGNAL("itemContextMenuRequested"), self._showItemContextMenu)
        # create popup menu for data products
        self._archived_dp_menu = menu = QMenu(self)
        self._archived_dp_menu_title = QLabel()
        self._archived_dp_menu_title.setMargin(5)
        self._archived_dp_menu_title_wa = wa = QWidgetAction(self)
        wa.setDefaultWidget(self._archived_dp_menu_title)
        menu.addAction(wa)
        menu.addSeparator()
        menu.addAction(pixmaps.editcopy.icon(), "Restore file(s) from archived copy", self._restoreItemFromArchive)
        menu.addAction(pixmaps.editpaste.icon(), "Copy pathname of archived copy to clipboard",
                       self._copyItemToClipboard)
        self._current_item = None
        # create popup menu for entries
        self._entry_menu = menu = QMenu(self)
        self._entry_menu_title = QLabel()
        self._entry_menu_title.setMargin(5)
        self._entry_menu_title_wa = wa = QWidgetAction(self)
        wa.setDefaultWidget(self._entry_menu_title)
        menu.addAction(wa)
        menu.addSeparator()
        menu.addAction(pixmaps.filefind.icon(), "View this log entry", self._viewEntryItem)
        menu.addAction(pixmaps.editdelete.icon(), "Delete this log entry", self._deleteSelectedEntries)
        # buttons at bottom
        log_lo.addSpacing(5)
        btnlo = QHBoxLayout()
        log_lo.addLayout(btnlo)
        self.wnewbtn = QPushButton(pixmaps.filenew.icon(), "New entry...", cw)
        self.wnewbtn.setToolTip("Click to add a new log entry.")
        # self.wnewbtn.setFlat(True)
        self.wnewbtn.setEnabled(False)
        btnlo.addWidget(self.wnewbtn)
        btnlo.addSpacing(5)
        self.weditbtn = QPushButton(pixmaps.filefind.icon(), "View entry...", cw)
        self.weditbtn.setToolTip("Click to view or edit the selected log entry/")
        # self.weditbtn.setFlat(True)
        self.weditbtn.setEnabled(False)
        self.connect(self.weditbtn, SIGNAL("clicked()"), self._viewEntryItem)
        btnlo.addWidget(self.weditbtn)
        btnlo.addSpacing(5)
        self.wdelbtn = QPushButton(pixmaps.editdelete.icon(), "Delete", cw)
        self.wdelbtn.setToolTip("Click to delete the selected log entry or entries.")
        # self.wdelbtn.setFlat(True)
        self.wdelbtn.setEnabled(False)
        self.connect(self.wdelbtn, SIGNAL("clicked()"), self._deleteSelectedEntries)
        btnlo.addWidget(self.wdelbtn)
        # enable status line
        self.statusBar().show()
        Purr.progressMessage = self.message
        self._prev_msg = None
        # editor dialog for new entry
        self.new_entry_dialog = Purr.Editors.NewLogEntryDialog(self)
        self.connect(self.new_entry_dialog, SIGNAL("newLogEntry"), self._newLogEntry)
        self.connect(self.new_entry_dialog, SIGNAL("filesSelected"), self._addDPFiles)
        self.connect(self.wnewbtn, SIGNAL("clicked()"), self.new_entry_dialog.show)
        self.connect(self.new_entry_dialog, SIGNAL("shown"), self._checkPounceStatus)
        # entry viewer dialog
        self.view_entry_dialog = Purr.Editors.ExistingLogEntryDialog(self)
        self.connect(self.view_entry_dialog, SIGNAL("previous()"), self._viewPrevEntry)
        self.connect(self.view_entry_dialog, SIGNAL("next()"), self._viewNextEntry)
        self.connect(self.view_entry_dialog, SIGNAL("viewPath"), self._viewPath)
        self.connect(self.view_entry_dialog, SIGNAL("filesSelected"), self._addDPFilesToOldEntry)
        self.connect(self.view_entry_dialog, SIGNAL("entryChanged"), self._entryChanged)
        # saving a data product to an older entry will automatically drop it from the
        # new entry dialog
        self.connect(self.view_entry_dialog, SIGNAL("creatingDataProduct"),
                     self.new_entry_dialog.dropDataProducts)
        # resize selves
        width = Config.getint('main-window-width', 512)
        height = Config.getint('main-window-height', 512)
        self.resize(QSize(width, height))
        # create timer for pouncing
        self._timer = QTimer(self)
        self.connect(self._timer, SIGNAL("timeout()"), self._rescan)
        # create dict mapping index.html paths to entry numbers
        self._index_paths = {}

    def resizeEvent(self, ev):
        QMainWindow.resizeEvent(self, ev)
        sz = ev.size()
        Config.set('main-window-width', sz.width())
        Config.set('main-window-height', sz.height())

    def closeEvent(self, ev):
        if self._hide_on_close:
            ev.ignore()
            self.hide()
            self.new_entry_dialog.hide()
        else:
            if self.purrer:
                self.purrer.detach()
            return QMainWindow.closeEvent(self, ev)

    def message(self, msg, ms=2000, sub=False):
        if sub:
            if self._prev_msg:
                msg = ": ".join((self._prev_msg, msg))
        else:
            self._prev_msg = msg
        self.statusBar().showMessage(msg, ms)
        QCoreApplication.processEvents(QEventLoop.ExcludeUserInputEvents)

    def _changeWatchedDirState(self, pathname, watching):
        self.purrer.setWatchingState(pathname, watching)
        # update dialogs if dir list has changed
        if watching == Purr.REMOVED:
            self.purrpipes.pop(pathname)
            dirs = [path for path, state in self.purrer.watchedDirectories()]
            self.new_entry_dialog.setDefaultDirs(*dirs)
            self.view_entry_dialog.setDefaultDirs(*dirs)
        pass

    def _showAddDirectoryDialog(self):
        dd = str(QFileDialog.getExistingDirectory(self, "PURR: Add a directory to monitor")).strip()
        if dd:
            # adds a watched directory. Default initial setting of 'watching' is POUNCE if all
            # directories are in POUNCE state, or WATCHED otherwise.
            watching = max(Purr.WATCHED,
                           min([state for path, state in self.purrer.watchedDirectories()] or [Purr.WATCHED]))
            self.purrer.addWatchedDirectory(dd, watching)
            self.purrpipes[dd] = Purr.Pipe.open(dd)
            self.wdirlist.add(dd, watching)
            # update dialogs since dir list has changed
            dirs = [path for path, state in self.purrer.watchedDirectories()]
            self.new_entry_dialog.setDefaultDirs(*dirs)
            self.view_entry_dialog.setDefaultDirs(*dirs)

    def detachPurrlog(self):
        self.wdirlist.clear()
        self.purrer and self.purrer.detach()
        self.purrer = None

    def hasPurrlog(self):
        return bool(self.purrer)

    def attachPurrlog(self, purrlog, watchdirs=[]):
        """Attaches Purr to the given purrlog directory. Arguments are passed to Purrer object as is."""
        # check purrer stack for a Purrer already watching this directory
        dprint(1, "attaching to purrlog", purrlog)
        for i, purrer in enumerate(self.purrer_stack):
            if os.path.samefile(purrer.logdir, purrlog):
                dprint(1, "Purrer object found on stack (#%d),reusing\n", i)
                # found? move to front of stack
                self.purrer_stack.pop(i)
                self.purrer_stack.insert(0, purrer)
                # update purrer with watched directories, in case they have changed
                for dd in (watchdirs or []):
                    purrer.addWatchedDirectory(dd, watching=None)
                break
        # no purrer found, make a new one
        else:
            dprint(1, "creating new Purrer object")
            try:
                purrer = Purr.Purrer(purrlog, watchdirs)
            except Purr.Purrer.LockedError as err:
                # check that we could attach, display message if not
                QMessageBox.warning(self, "Catfight!", """<P><NOBR>It appears that another PURR process (%s)</NOBR>
          is already attached to <tt>%s</tt>, so we're not allowed to touch it. You should exit the other PURR
          process first.</P>""" % (err.args[0], os.path.abspath(purrlog)), QMessageBox.Ok, 0)
                return False
            except Purr.Purrer.LockFailError as err:
                QMessageBox.warning(self, "Failed to obtain lock", """<P><NOBR>PURR was unable to obtain a lock</NOBR>
          on directory <tt>%s</tt> (error was "%s"). The most likely cause is insufficient permissions.</P>""" % (
                os.path.abspath(purrlog), err.args[0]), QMessageBox.Ok, 0)
                return False
            self.purrer_stack.insert(0, purrer)
            # discard end of stack
            self.purrer_stack = self.purrer_stack[:3]
            # attach signals
            self.connect(purrer, SIGNAL("disappearedFile"),
                         self.new_entry_dialog.dropDataProducts)
            self.connect(purrer, SIGNAL("disappearedFile"),
                         self.view_entry_dialog.dropDataProducts)
        # have we changed the current purrer? Update our state then
        # reopen Purr pipes
        self.purrpipes = {}
        for dd, state in purrer.watchedDirectories():
            self.purrpipes[dd] = Purr.Pipe.open(dd)
        if purrer is not self.purrer:
            self.message("Attached to %s" % purrer.logdir, ms=10000)
            dprint(1, "current Purrer changed, updating state")
            # set window title
            path = Kittens.utils.collapseuser(os.path.join(purrer.logdir, ''))
            self.setWindowTitle("PURR - %s" % path)
            # other init
            self.purrer = purrer
            self.new_entry_dialog.hide()
            self.new_entry_dialog.reset()
            dirs = [path for path, state in purrer.watchedDirectories()]
            self.new_entry_dialog.setDefaultDirs(*dirs)
            self.view_entry_dialog.setDefaultDirs(*dirs)
            self.view_entry_dialog.hide()
            self.viewer_dialog.hide()
            self._viewing_ientry = None
            self._setEntries(self.purrer.getLogEntries())
            #      print self._index_paths
            self._viewer_timestamp = None
            self._updateViewer()
            self._updateNames()
            # update directory widgets
            self.wdirlist.clear()
            for pathname, state in purrer.watchedDirectories():
                self.wdirlist.add(pathname, state)
            # Reset _pounce to false -- this will cause checkPounceStatus() into a rescan
            self._pounce = False
            self._checkPounceStatus()
        return True

    def setLogTitle(self, title):
        if self.purrer:
            if title != self.purrer.logtitle:
                self.purrer.setLogTitle(title)
                self._updateViewer()
            self._updateNames()

    def _updateNames(self):
        self.wnewbtn.setEnabled(True)
        self.wviewlog.setEnabled(True)
        self._about_dialog.setText(self.about_message + """
      <P>Your current log resides in:<PRE>  <tt>%s</tt></PRE>To see your log in all its HTML-rendered
      glory, point your browser to <tt>index.html</tt> therein, or use the handy "View" button provided by PURR.</P>

      <P>Your current working directories are:</P>
      <P>%s</P>
      """ % (self.purrer.logdir,
             "".join(["<PRE>  <tt>%s</tt></PRE>" % name for name, state in self.purrer.watchedDirectories()])
             ))
        title = self.purrer.logtitle or "Unnamed log"
        self.title_editor.setText(title)
        self.viewer_dialog.setWindowTitle(title)

    def _showViewerDialog(self):
        self._updateViewer(True)
        self.viewer_dialog.show()

    @staticmethod
    def fileModTime(path):
        try:
            return os.path.getmtime(path)
        except:
            return None

    def _updateViewer(self, force=False):
        """Updates the viewer dialog.
        If dialog is not visible and force=False, does nothing.
        Otherwise, checks the mtime of the current purrer index.html file against self._viewer_timestamp.
        If it is newer, reloads it.
        """
        if not force and not self.viewer_dialog.isVisible():
            return
        # default text if nothing is found
        path = self.purrer.indexfile
        mtime = self.fileModTime(path)
        # return if file is older than our content
        if mtime and mtime <= (self._viewer_timestamp or 0):
            return
        busy = BusyIndicator()
        self.viewer_dialog.setDocument(path, empty=
        "<P>Nothing in the log yet. Try adding some log entries.</P>")
        self.viewer_dialog.reload()
        self.viewer_dialog.setLabel("""<P>Below is your full HTML-rendered log. Note that this is 
      only a bare-bones viewer, so only a limited set of links will work. 
      For a fully-functional view, use a proper HTML browser to look at the index file residing here:<BR>
      <tt>%s</tt></P>
      """ % self.purrer.indexfile)
        self._viewer_timestamp = mtime

    def _setEntries(self, entries):
        self.etw.clear()
        item = None
        self._index_paths = {}
        self._index_paths[os.path.abspath(self.purrer.indexfile)] = -1
        for i, entry in enumerate(entries):
            item = self._addEntryItem(entry, i, item)
            self._index_paths[os.path.abspath(entry.index_file)] = i
        self.etw.resizeColumnToContents(0)

    def _titleChanged(self):
        self.setLogTitle(str(self.title_editor.text()))

    def _checkPounceStatus(self):
        ## pounce = bool([ entry for entry in self._dir_entries.itervalues() if entry.watching ])
        pounce = bool([path for path, state in self.purrer.watchedDirectories() if state >= Purr.WATCHED])
        # rescan, if going from not-pounce to pounce
        if pounce and not self._pounce:
            self._rescan()
        self._pounce = pounce
        # start timer -- we need it running to check the purr pipe, anyway
        self._timer.start(2000)

    def _forceRescan(self):
        if not self.purrer:
            self.attachDirectory('.')
        self._rescan(force=True)

    def _rescan(self, force=False):
        if not self.purrer:
            return
        # if pounce is on, tell the Purrer to rescan directories
        if self._pounce or force:
            dps = self.purrer.rescan()
            if dps:
                filenames = [dp.filename for dp in dps]
                dprint(2, "new data products:", filenames)
                self.message("Pounced on " + ", ".join(filenames))
                if self.new_entry_dialog.addDataProducts(dps):
                    dprint(2, "showing dialog")
                    self.new_entry_dialog.show()
        # else read stuff from pipe
        for pipe in list(self.purrpipes.values()):
            do_show = False
            for command, show, content in pipe.read():
                if command == "title":
                    self.new_entry_dialog.suggestTitle(content)
                elif command == "comment":
                    self.new_entry_dialog.addComment(content)
                elif command == "pounce":
                    self.new_entry_dialog.addDataProducts(self.purrer.makeDataProducts(
                        [(content, not show)], unbanish=True))
                else:
                    print(("Unknown command received from Purr pipe: ", command))
                    continue
                do_show = do_show or show
            if do_show:
                self.new_entry_dialog.show()

    def _addDPFiles(self, *files):
        """callback to add DPs corresponding to files."""
        # quiet flag is always true
        self.new_entry_dialog.addDataProducts(self.purrer.makeDataProducts(
            [(file, True) for file in files], unbanish=True, unignore=True))

    def _addDPFilesToOldEntry(self, *files):
        """callback to add DPs corresponding to files."""
        # quiet flag is always true
        self.view_entry_dialog.addDataProducts(self.purrer.makeDataProducts(
            [(file, True) for file in files], unbanish=True, unignore=True))

    def _entrySelectionChanged(self):
        selected = [item for item in self.etw.iterator(self.etw.Iterator.Selected) if item._ientry is not None]
        self.weditbtn.setEnabled(len(selected) == 1)
        self.wdelbtn.setEnabled(bool(selected))

    def _viewEntryItem(self, item=None, *dum):
        """Pops up the viewer dialog for the entry associated with the given item.
        If 'item' is None, looks for a selected item in the listview.
        The dum arguments are for connecting this to QTreeWidget signals such as doubleClicked().
        """
        # if item not set, look for selected items in listview. Only 1 must be selected.
        select = True
        if item is None:
            selected = [item for item in self.etw.iterator(self.etw.Iterator.Selected) if item._ientry is not None]
            if len(selected) != 1:
                return
            item = selected[0]
            select = False;  # already selected
        else:
            # make sure item is open -- the click will cause it to close
            self.etw.expandItem(item)
        # show dialog
        ientry = getattr(item, '_ientry', None)
        if ientry is not None:
            self._viewEntryNumber(ientry, select=select)

    def _viewEntryNumber(self, ientry, select=True):
        """views entry #ientry. Also selects entry in listview if select=True"""
        # pass entry to viewer dialog
        self._viewing_ientry = ientry
        entry = self.purrer.entries[ientry]
        busy = BusyIndicator()
        self.view_entry_dialog.viewEntry(entry,
                                         prev=ientry > 0 and self.purrer.entries[ientry - 1],
                                         next=ientry < len(self.purrer.entries) - 1 and self.purrer.entries[ientry + 1])
        self.view_entry_dialog.show()
        # select entry in listview
        if select:
            self.etw.clearSelection()
            self.etw.setItemSelected(self.etw.topLevelItem(ientry), True)

    def _viewPrevEntry(self):
        if self._viewing_ientry is not None and self._viewing_ientry > 0:
            self._viewEntryNumber(self._viewing_ientry - 1)

    def _viewNextEntry(self):
        if self._viewing_ientry is not None and self._viewing_ientry < len(self.purrer.entries) - 1:
            self._viewEntryNumber(self._viewing_ientry + 1)

    def _viewPath(self, path):
        num = self._index_paths.get(os.path.abspath(path), None)
        if num is None:
            return
        elif num == -1:
            self.view_entry_dialog.hide()
            self._showViewerDialog()
        else:
            self._viewEntryNumber(num)

    def _showItemContextMenu(self, item, point, col):
        """Callback for contextMenuRequested() signal. Pops up item menu, if defined"""
        menu = getattr(item, '_menu', None)
        if menu:
            settitle = getattr(item, '_set_menu_title', None)
            if settitle:
                settitle()
            # self._current_item tells callbacks what item the menu was referring to
            point = self.etw.mapToGlobal(point)
            self._current_item = item
            self.etw.clearSelection()
            self.etw.setItemSelected(item, True)
            menu.exec_(point)
        else:
            self._current_item = None

    def _copyItemToClipboard(self):
        """Callback for item menu."""
        if self._current_item is None:
            return
        dp = getattr(self._current_item, '_dp', None)
        if dp and dp.archived:
            path = dp.fullpath.replace(" ", "\\ ")
            QApplication.clipboard().setText(path, QClipboard.Clipboard)
            QApplication.clipboard().setText(path, QClipboard.Selection)

    def _restoreItemFromArchive(self):
        """Callback for item menu."""
        if self._current_item is None:
            return
        dp = getattr(self._current_item, '_dp', None)
        if dp and dp.archived:
            dp.restore_from_archive(parent=self)

    def _deleteSelectedEntries(self):
        remaining_entries = []
        del_entries = list(self.etw.iterator(self.etw.Iterator.Selected))
        remaining_entries = list(self.etw.iterator(self.etw.Iterator.Unselected))
        if not del_entries:
            return
        hide_viewer = bool([item for item in del_entries if self._viewing_ientry == item._ientry])
        del_entries = [self.purrer.entries[self.etw.indexOfTopLevelItem(item)] for item in del_entries]
        remaining_entries = [self.purrer.entries[self.etw.indexOfTopLevelItem(item)] for item in remaining_entries]
        # ask for confirmation
        if len(del_entries) == 1:
            msg = """<P><NOBR>Permanently delete the log entry</NOBR> "%s"?</P>""" % del_entries[0].title
            if del_entries[0].dps:
                msg += """<P>%d data product(s) saved with this
                  entry will be deleted as well.</P>""" % len(del_entries[0].dps)
        else:
            msg = """<P>Permanently delete the %d selected log entries?</P>""" % len(del_entries)
            ndp = 0
            for entry in del_entries:
                ndp += len([dp for dp in entry.dps if not dp.ignored])
            if ndp:
                msg += """<P>%d data product(s) saved with these entries will be deleted as well.</P>""" % ndp
        if QMessageBox.warning(self, "Deleting log entries", msg,
                               QMessageBox.Yes, QMessageBox.No) != QMessageBox.Yes:
            return
        if hide_viewer:
            self.view_entry_dialog.hide()
        # reset entries in purrer and in our log window
        self._setEntries(remaining_entries)
        self.purrer.deleteLogEntries(del_entries)
        #    self.purrer.setLogEntries(remaining_entries)
        # log will have changed, so update the viewer
        self._updateViewer()
        # delete entry files
        for entry in del_entries:
            entry.remove_directory()

    def _addEntryItem(self, entry, number, after):
        item = entry.tw_item = QTreeWidgetItem(self.etw, after)
        timelabel = self._make_time_label(entry.timestamp)
        item.setText(0, timelabel)
        item.setText(1, " " + (entry.title or ""))
        item.setToolTip(1, entry.title)
        if entry.comment:
            item.setText(2, " " + entry.comment.split('\n')[0])
            item.setToolTip(2, "<P>" + entry.comment.replace("<", "&lt;").replace(">", "&gt;"). \
                            replace("\n\n", "</P><P>").replace("\n", "</P><P>") + "</P>")
        item._ientry = number
        item._dp = None
        item._menu = self._entry_menu
        item._set_menu_title = lambda: self._entry_menu_title.setText('"%s"' % entry.title)
        # now make subitems for DPs
        subitem = None
        for dp in entry.dps:
            if not dp.ignored:
                subitem = self._addDPSubItem(dp, item, subitem)
        self.etw.collapseItem(item)
        self.etw.header().headerDataChanged(Qt.Horizontal, 0, 2)
        return item

    def _addDPSubItem(self, dp, parent, after):
        item = QTreeWidgetItem(parent, after)
        item.setText(1, dp.filename)
        item.setToolTip(1, dp.filename)
        item.setText(2, dp.comment or "")
        item.setToolTip(2, dp.comment or "")
        item._ientry = None
        item._dp = dp
        item._menu = self._archived_dp_menu
        item._set_menu_title = lambda: self._archived_dp_menu_title.setText(os.path.basename(dp.filename))
        return item

    def _make_time_label(self, timestamp):
        return time.strftime("%b %d %H:%M", time.localtime(timestamp))

    def _newLogEntry(self, entry):
        """This is called when a new log entry is created"""
        # add entry to purrer
        self.purrer.addLogEntry(entry)
        # add entry to listview if it is not an ignored entry
        # (ignored entries only carry information about DPs to be ignored)
        if not entry.ignore:
            if self.etw.topLevelItemCount():
                lastitem = self.etw.topLevelItem(self.etw.topLevelItemCount() - 1)
            else:
                lastitem = None
            self._addEntryItem(entry, len(self.purrer.entries) - 1, lastitem)
            self._index_paths[os.path.abspath(entry.index_file)] = len(self.purrer.entries) - 1
        # log will have changed, so update the viewer
        if not entry.ignore:
            self._updateViewer()
            self.show()

    def _entryChanged(self, entry):
        """This is called when a log entry is changed"""
        # resave the log
        self.purrer.save()
        # redo entry item
        if entry.tw_item:
            number = entry.tw_item._ientry
            entry.tw_item = None
            self.etw.takeTopLevelItem(number)
            if number:
                after = self.etw.topLevelItem(number - 1)
            else:
                after = None
            self._addEntryItem(entry, number, after)
        # log will have changed, so update the viewer
        self._updateViewer()

    def _regenerateLog(self):
        if QMessageBox.question(self.viewer_dialog, "Regenerate log", """<P><NOBR>Do you really want to regenerate the
      entire</NOBR> log? This can be a time-consuming operation.</P>""",
                                QMessageBox.Yes, QMessageBox.No) != QMessageBox.Yes:
            return
        self.purrer.save(refresh=True)
        self._updateViewer()
