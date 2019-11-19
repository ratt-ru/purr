# -*- coding: utf-8 -*-
import glob
import os
import os.path

import Kittens.utils
from PyQt4.Qt import QWidget, QDialog, QWizard, QWizardPage, QButtonGroup, QVBoxLayout, QRadioButton, QObject, SIGNAL, QHBoxLayout, QLineEdit, QPushButton, QFileDialog, QMessageBox

import Purr
from Purr import pixmaps


class Error(RuntimeError):
    def __init__(self, message):
        RuntimeError.__init__(self)
        self.error_message = message


wizard_dialog = None


def startWizard(args, mainwin, modal=True):
    """
    Parses list of directories ('args') and attaches to purrlogs appropriately.
    'mainwin' is a Purr.MainWindow object.

    Return value:
      * if modal=True: True if arguments parse OK and Purr.MainWindow should be shown, False on error.
      * if modal=False: True if attached to purrlog and Purr.MainWindow should be shown, False otherwise.

    If modal=False, it will keep displaying the startup dialog as a modeless dialog, and attach the
  mainwin to the specified purrlog when the dialog is closed.

    Use cases:
     $ purr <dirname> [<more dirs>]
        1. If dirname does not exist:
          * find other purrlogs in parent dir
          * pop up wizard, with the name as the default "create" option, and create selected
        2. If dirname exists:
          2a. Not a directory: report error
          2b. If dir is a purrlog, attach and add dirs
          2c. If dir contains 1 valid purrlog, attach, and add more dirs.
          2d. If dir contains 2+ purrlogs, offer choice (or create new), add more dirs
          2e. If dir contains no purrlogs, offer to create one (or to attach to one), add "more dirs" to watchlist if creating new, ignore if attaching
     $ purr
         * same as "purr ."
     $ from meqbrowser, when cd into a directory:
         * if purr dialog is visible, do same as "purr ."
     $ from meqbrowser, when purr button is pressed and purr is not yet visible
         * do "purr ."
     $ from Cattery.Calico, when an MS is selected:
         * do purr MS.purrlog .
    """

    args = args or [os.getcwd()]
    dirname = os.path.abspath(args[0])
    moredirs = args[1:]

    # case 1: dirname does not exist, or refers to a non-directory
    if not os.path.exists(dirname) or not os.path.isdir(dirname):
        message = """To begin with, PURR must load an existing purrlog, or start a new purrlog. <tt>%s</tt> does not look to be an existing purrlog.
            What would you like to do?""" % Kittens.utils.collapseuser(dirname)
        create = dirname
        dirname = os.getcwd()
        parent = os.path.dirname(os.path.normpath(create)) or os.getcwd()
        # if parent is valid dir, find purrlogs in parent (to offer as an option)
        if os.path.isdir(parent):
            purrlogs = list(filter(Purr.Purrer.is_purrlog, glob.glob(os.path.join(parent, "*"))))
        # else use "." as dirname, and do not offer any purrlogs
        else:
            purrlogs = []
    # case 2: dirname exists:
    else:
        create = None
        # case 2b: is a valid purrlog
        if Purr.Purrer.is_purrlog(dirname):
            mainwin.attachPurrlog(dirname, moredirs)
            mainwin.show()
            return True
        # case 2c-2e. Look for purrlogs in dirname
        purrlogs = list(filter(Purr.Purrer.is_purrlog, glob.glob(os.path.join(dirname, "*"))))
        # case 2c: exactly one purrlog. Attach without asking.
        if len(purrlogs) == 1:
            mainwin.show()
            mainwin.attachPurrlog(purrlogs[0], moredirs)
            return True
        # else setup messages
        if purrlogs:
            message = """To begin with, PURR must load an existing purrlog, or start a new purrlog. The directory <tt>%s</tt> contains
          several purrlogs. What would you like to do?""" % Kittens.utils.collapseuser(dirname)
        else:
            message = """To begin with, PURR must load an existing purrlog, or create a new purrlog. The directory <tt>%s</tt> contains
          no purrlogs. What would you like to do?""" % Kittens.utils.collapseuser(dirname)

    # case 1, 2d or 2e: make wizard dialog

    # kill old wizard, if showing
    global wizard_dialog
    if wizard_dialog:
        wizard_dialog.hide()
        dum = QWidget()
        wizard_dialog.setParent(dum)
        dum = wizard_dialog = None

    # create new wizard
    wizard_dialog = PurrStartupWizard(mainwin, dirname, purrlogs, moredirs=moredirs, create=create, message=message)

    if modal:
        if wizard_dialog.exec_() == QDialog.Rejected:
            return False
        return True;
    else:
        wizard_dialog.setModal(False)
        wizard_dialog.show()
        return False


class PurrStartupWizard(QWizard):
    class StartPage(QWizardPage):
        def __init__(self, dirname, purrlogs, parent=None, create=None, message=None):
            QWizardPage.__init__(self, parent)
            self.dirname = dirname
            self.purrlogs = purrlogs or []
            bg = QButtonGroup(self)
            lo = QVBoxLayout()
            self.setLayout(lo)
            # set page titles
            self.setTitle("Starting PURR")
            message and self.setSubTitle(message)
            if not purrlogs:
                self.rbs_log = []
            else:
                # add options for existing purrlogs
                self.rbs_log = [QRadioButton("Load %s" % Kittens.utils.collapseuser(log)) for log in purrlogs]
                for rb in self.rbs_log:
                    lo.addWidget(rb)
                    bg.addButton(rb)
                    QObject.connect(rb, SIGNAL("toggled(bool)"), self.checkCompleteness)
                self.rbs_log[0].setChecked(True)
            # add option to load another purrlog
            lo1 = QHBoxLayout()
            self.rb_other = QRadioButton("Load purrlog from:")
            lo1.addWidget(self.rb_other)
            bg.addButton(self.rb_other)
            self.wother = QLineEdit()
            self.wother.setReadOnly(True)
            lo1.addWidget(self.wother, 1)
            pb = QPushButton(pixmaps.folder_open.icon(), "")
            QObject.connect(pb, SIGNAL("clicked()"), self._select_other_dialog)
            QObject.connect(self.rb_other, SIGNAL("toggled(bool)"), pb.setEnabled)
            QObject.connect(self.rb_other, SIGNAL("toggled(bool)"), self.wother.setEnabled)
            QObject.connect(self.rb_other, SIGNAL("toggled(bool)"), self.checkCompleteness)
            pb.setEnabled(False)
            self.wother.setEnabled(False)
            lo1.addWidget(pb)
            lo.addLayout(lo1)
            self.load_path = None

            # add option to create new purrlog
            lo1 = QHBoxLayout()
            self.rb_create = QRadioButton("Create new purrlog:")
            lo1.addWidget(self.rb_create)
            bg.addButton(self.rb_create)
            self.wcreate = QLineEdit()
            lo1.addWidget(self.wcreate, 1)
            pb = QPushButton(pixmaps.folder_open.icon(), "")
            QObject.connect(pb, SIGNAL("clicked()"), self._select_create_dialog)
            QObject.connect(self.rb_create, SIGNAL("toggled(bool)"), pb.setEnabled)
            QObject.connect(self.rb_create, SIGNAL("toggled(bool)"), self.wcreate.setEnabled)
            QObject.connect(self.rb_create, SIGNAL("toggled(bool)"), self.checkCompleteness)
            QObject.connect(self.wcreate, SIGNAL("editingFinished()"), self._validate_create_filename)
            pb.setEnabled(False)
            self.wcreate.setEnabled(False)
            # this holds the last validated name
            self._validated_create_path = None
            self._validated_result = False
            # generate default name for a new purrlog
            self.create_path = os.path.join(dirname, "purrlog")
            num = 0
            while os.path.exists(self.create_path):
                self.create_path = os.path.join(dirname, "purrlog.%d" % num)
                num += 1
            # This will be not None as long as a valid name is entered
            self.create_path = Kittens.utils.collapseuser(os.path.normpath(self.create_path))
            if create:
                self.wcreate.setText(create or Kittens.utils.collapseuser(create))
                # this will emit checkCompleteness(), causing a _validate_create_filename() call, causing the content of the wcreate widget
                # to be validated and copied to create_path if valid, or reset from create_path if invalid
                self.rb_create.setChecked(True)
            else:
                self.wcreate.setText(self.create_path)

            lo1.addWidget(pb)
            lo.addLayout(lo1)

            # make create option default, if no purrlogs
            if not purrlogs:
                self.rb_create.setChecked(True)

        def _select_other_dialog(self):
            path = str(QFileDialog.getExistingDirectory(self, "Select purrlog", self.dirname))
            if not path:
                return
            if not Purr.Purrer.is_purrlog(path):
                QMessageBox.warning(self, "Invalid purrlog",
                                    "The path you have selected, <tt>%s</tt>, does not refer to a valid purrlog." % Kittens.utils.collapseuser(
                                        path))
                return
            self.load_path = path
            self.wother.setText(Kittens.utils.collapseuser(path))
            self.checkCompleteness()

        def _validate_create_filename(self, path=None, check=True):
            if path is None:
                path = str(self.wcreate.text())
            # if we have already validated this path, then return the last validation result.
            # This is mostly to keep from bombarding the user with repeated error dialogs.
            if self._validated_create_path == path:
                return self._validated_result
            self._validated_create_path = path
            self._validated_result = False;  # set to True if all checks pass
            # now process the path. Normalize it, and expand "~"
            path = os.path.expanduser(os.path.normpath(path))
            # if not absolute, join to current directory
            if not os.path.isabs(path):
                path = os.path.join(self.dirname, path)
            # collapse to "~" (for error messages)
            path0 = Kittens.utils.collapseuser(path)
            if os.path.exists(path):
                QMessageBox.warning(self, "Can't create purrlog",
                                    """Unable to create purrlog <tt>%s</tt>: file or directory already exists. Please select another name""" % path0)
                self.create_path and self.wcreate.setText(Kittens.utils.collapseuser(self.create_path))
                return False
            if not os.access(os.path.dirname(os.path.normpath(path)) or '.', os.W_OK):
                QMessageBox.warning(self, "Can't create purrlog",
                                    """Unable to create purrlog <tt>%s</tt>: can't write to parent directory. Please select another path.""" % path0)
                self.create_path and self.wcreate.setText(Kittens.utils.collapseuser(self.create_path))
                return False
            self.create_path = path
            self.wcreate.setText(path0)
            self._validated_result = True;  # set to True if all checks pass
            if check:
                self.checkCompleteness()
            return True

        def _select_create_dialog(self):
            path = str(QFileDialog.getSaveFileName(self, "Create new purrlog", self.create_path))
            if path:
                self._validate_create_filename(path)

        def checkCompleteness(self, toggled=None):
            if toggled and hasattr(self, 'rb_other') and self.rb_other.isChecked() and not self.load_path:
                self._select_other_dialog()
            else:
                self.emit(SIGNAL("completeChanged()"))

        def isComplete(self):
            if hasattr(self, 'rb_create') and self.rb_create.isChecked():
                return self._validate_create_filename(check=False) and bool(self.create_path)
            if hasattr(self, 'rb_other') and self.rb_other.isChecked():
                return bool(self.load_path)
            return True

        def selectedPath(self):
            for (rb, log) in zip(self.rbs_log, self.purrlogs):
                if rb.isChecked():
                    return log
            if self.rb_other.isChecked():
                return self.load_path
            if self.rb_create.isChecked():
                return self.create_path
            return None

    def __init__(self, mainwin, dirname, purrlogs, moredirs=[], create=None, message=None):
        QWizard.__init__(self, mainwin)
        self.setWindowTitle("Starting PURR")
        self.setPixmap(QWizard.LogoPixmap, pixmaps.purr_logo.pm())
        self.setOption(QWizard.NoBackButtonOnStartPage)
        self.setButtonText(QWizard.FinishButton, "Proceed")
        # create start page
        self._startpage = self.StartPage(dirname, purrlogs, create=create, message=message)
        self.addPage(self._startpage)
        # internal state
        self._dirname = dirname
        self._mainwin = mainwin
        self._moredirs = moredirs

    def done(self, code):
        if code == QDialog.Accepted:
            # check path, set code to rejected if none set
            path = self._startpage.selectedPath()
            if not path:
                print("No path selected in StartupWizard. This is probably a bug, please report it!")
                code = QDialog.Rejected
            else:
                # show the main window
                self._mainwin.show()
                # if attaching to existing purrlog, cancel the moredirs argument
                # if creating new purrlog, add parent directory to watchlist
                moredirs = None if os.path.exists(path) else [self._dirname] + list(self._moredirs)
                self._mainwin.attachPurrlog(path, moredirs)
        return QDialog.done(self, code)

    def selectedPath(self):
        return self._startpage.selectedPath()

# class PurrlogSelectWizard (QDialog):
#  def __init__(self,parent,dirname,purrlogs):
#    QDialog.__init__(self,parent)
#    self.setWindowTitle("PURR Startup Wizard")
#    self._currier = Kittens.utils.PersistentCurrier()
#    self._lo = QVBoxLayout(self)
#    self._lo.setSpacing(0)
#    for log in purrlogs:
#      self.button(pixmaps.purr_logo.icon(),"Load %s"%Kittens.utils.collapseuser(log),self._currier.curry(self._load_log,log))
#    self.button(pixmaps.purr_logo.icon(),"Load a different purrlog...",self._load_other_log)
#    self.button(pixmaps.purr_logo.icon(),"Create new purrlog in %s..."%Kittens.utils.collapseuser(dirname),self._create_log)
#    self._lo.addSpacing(10)
#    self.button(pixmaps.red_round_cross.icon(),"Cancel",self.reject)
#
#  def button (self,icon,text,callback):
#    pb = QToolButton(self)
#    pb.setIcon(icon)
#    pb.setText(text)
#    pb.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
#    pb.setSizePolicy(QSizePolicy.Minimum,QSizePolicy.MinimumExpanding)
#    # pb.setFlat(True)
#    self._lo.addWidget(pb)
#    QObject.connect(pb,SIGNAL("clicked()"),callback)
#    return pb
#
#  def _load_log (self,logname):
#    pass
#
#  def _create_log (self):
#    pass
#
#  def _load_other_log (self):
#    dialog = QFileDialog(parent,"Open or create purrlog",dirname,"*purrlog")
#    try:
#      dialog.setOption(QFileDialog.ShowDirsOnly)
#      dialog.setFileMode(QFileDialog.Directory)
#    except AttributeError: # Qt 4.4 has no setOption
#      dialog.setFileMode(QFileDialog.DirectoryOnly)
#    if purrlogs:
#      dialog.setSidebarUrls(map(QUrl,purrlogs))
#    if not dialog.exec_():
#      return False
#    logname = str(dialog.selectedFiles()[0])
#    mainwin.show()
#    mainwin.attachPurrlog(logname,moredirs)
#    return True
