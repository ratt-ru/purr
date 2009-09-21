# -*- coding: utf-8 -*-
_tdl_no_reimport = True;

import os.path
import time

from PyQt4.Qt import *

import Purr
import Purr.Editors
import Purr.LogEntry
import Purr.Pipe
from Purr import Config,pixmaps,dprint,dprintf
import Kittens.widgets
import Kittens.utils

class BusyIndicator (object):
  def __init__ (self):
    QApplication.setOverrideCursor(QCursor(Qt.WaitCursor));
  def __del__ (self):
    QApplication.restoreOverrideCursor();

class HTMLViewerDialog (QDialog):
  """This class implements a dialog to view a piece of HTML text.""";
  def __init__ (self,parent,config_name=None,buttons=[],*args):
    """Creates dialog.
    'config_name' is used to get/set default window size from Config object
    'buttons' can be a list of names or (QPixmapWrapper,name[,tooltip]) tuples to provide 
    custom buttons at the bottom of the dialog. When a button is clicked, the dialog 
    emits SIGNAL("name").
    A "Close" button is always provided, this simply hides the dialog.
    """;
    QDialog.__init__(self,parent,*args);
    self.setModal(False);
    lo = QVBoxLayout(self);
    # create viewer
    self.label = QLabel(self);
    self.label.setMargin(5);
    self.label.setWordWrap(True);
    lo.addWidget(self.label);
    self.label.hide();
    self.viewer = QTextBrowser(self);
    lo.addWidget(self.viewer);
    # self.viewer.setReadOnly(True);
    self.viewer.setSizePolicy(QSizePolicy.Expanding,QSizePolicy.Expanding);
    QObject.connect(self.viewer,SIGNAL("anchorClicked(const QUrl &)"),self._resetSource);
    self._source = None;
    lo.addSpacing(5);
    # create button bar
    btnfr = QFrame(self);
    btnfr.setSizePolicy(QSizePolicy.MinimumExpanding,QSizePolicy.Fixed);
    # btnfr.setMargin(5);
    lo.addWidget(btnfr);
    lo.addSpacing(5);
    btnfr_lo = QHBoxLayout(btnfr);
    btnfr_lo.setMargin(5);
    # add user buttons
    self._user_buttons = {};
    for name in buttons:
      if isinstance(name,str):
        btn = QPushButton(name,btnfr);
      elif isinstance(name,(list,tuple)):
        if len(name) < 3:
          pixmap,name = name;
          tip = None;
        else:
          pixmap,name,tip = name;
        btn = QPushButton(pixmap.icon(),name,btnfr);
        if tip:
          btn.setToolTip(tip);
      self._user_buttons[name] = btn;
      btn._clicked = Kittens.utils.curry(self.emit,SIGNAL(name));
      self.connect(btn,SIGNAL("clicked()"),btn._clicked);
      btnfr_lo.addWidget(btn,1);
    # add a Close button
    btnfr_lo.addStretch(100);
    closebtn = QPushButton(pixmaps.grey_round_cross.icon(),"Close",btnfr);
    self.connect(closebtn,SIGNAL("clicked()"),self.hide);
    btnfr_lo.addWidget(closebtn,1);
    # resize selves
    self.config_name = config_name or "html-viewer";
    width = Config.getint('%s-width'%self.config_name,512);
    height = Config.getint('%s-height'%self.config_name,512);
    self.resize(QSize(width,height));
   
  def resizeEvent (self,ev):
    QDialog.resizeEvent(self,ev);
    sz = ev.size();
    Config.set('%s-width'%self.config_name,sz.width());
    Config.set('%s-height'%self.config_name,sz.height());
    
  def setDocument (self,filename):
    """Sets the HTML text to be displayed. """;
    self._source = QUrl.fromLocalFile(filename);
    self.viewer.setSource(self._source);
    
  def _resetSource (self,*dum):
    self.viewer.setSource(self._source);

  def reload (self):
    self.viewer.reload();
    
  def setLabel (self,label=None):
    if label is None:
      self.label.hide();
    else:
      self.label.setText(label);
      self.label.show();

class MainWindow (QMainWindow):
  
  about_message = """
    <P>PURR ("<B>P</B>URR is <B>U</B>seful for <B>R</B>emembering <B>R</B>eductions", for those working with
    a stable version, or "<B>P</B>URR <B>U</B>sually <B>R</B>emembers <B>R</B>eductions", for those 
    working with a development version, or "<B>P</B>URR <B>U</B>sed to <B>R</B>emember <B>R</B>eductions", 
    for those working with a broken version) is a tool for
    automatically keeping a log of your data reduction operations. PURR will watch your working directories
    for new files (called "data products"), and upon seeing any, it can "pounce" -- that is, offer
    you the option of saving them to a log, along with descriptive comments. It will then
    generate an HTML page with a rendering of your log and data products.</P>
  """;
  
  pounce_help = \
      """<P>This control determines what PURR does about updated files.</P>
      
      <P>If <B>pounce & show</B> is selected, PURR will periodically check your working directories for new
      or updated files, and pop up the "New Log Entry" dialog when it detects any.</P>
      
      <P><B>Pounce</B> alone is less obtrusive. PURR will watch for files and quietly add them to the "New Log Entry" dialog, but will not display the dialog. You can display the dialog yourself by
      clicking on "New entry".</P>
      
      <P>If <B>ignore</B> is selected, PURR will not watch for changes at all. In this mode, you can use the "Rescan" button to check for new or updated files.</P>
      """;

  # constants for autopounce modes
  PounceIgnore = 0;
  PouncePounce = 1;
  PounceShow = 2;
  # labels for the pounce mode combobox
  pounce_labels = [ "ignore","pounce","pounce & show" ];
  
  def __init__ (self,parent,hide_on_close=False):
    QMainWindow.__init__(self,parent);
    self._hide_on_close = hide_on_close;
    # replace the BusyIndicator class with a GUI-aware one
    Purr.BusyIndicator = BusyIndicator;
    # autopounce is on if GUI checkbox is on
    # pounce is on if autopounce is on, or the new Entry dialog is visible.
    self._autopounce = self.PounceIgnore;
    self._pounce = False;
    # we keep a small stack of previously active purrers. This makes directory changes
    # faster (when going back and forth between dirs)
    # current purrer
    self.purrer = None;
    self.purrer_stack = [];
    # Purr pipe for receiving remote commands
    self.purrpipe = None;
    # init GUI
    self.setWindowTitle("PURR");
    self.setWindowIcon(pixmaps.purr_logo.icon());
    cw = QWidget(self);
    self.setCentralWidget(cw);
    cwlo = QVBoxLayout(cw);
    cwlo.setMargin(5);
    cwlo.setSpacing(0);
    toplo = QHBoxLayout(); cwlo.addLayout(toplo);
    label = QLabel("Updated files:",cw);
    label.setToolTip(self.pounce_help);
    toplo.addWidget(label);
    toplo.addSpacing(5);
    self.wpounce = QComboBox(cw);
    self.wpounce.setToolTip(self.pounce_help);
    self.wpounce.addItems(self.pounce_labels);
    self.wpounce.setCurrentIndex(self._autopounce);
    self.connect(self.wpounce,SIGNAL("activated(int)"),self.setPounceMode);
    toplo.addWidget(self.wpounce,1);
    toplo.addSpacing(5);
    wrescan = QPushButton(pixmaps.blue_round_reload.icon(),"Rescan",cw);
    wrescan.setToolTip("Checks your working directories for new or updated files.");
    self.connect(wrescan,SIGNAL("clicked()"),self._forceRescan);
    toplo.addWidget(wrescan);
    toplo.addStretch(1);
    about_btn = QPushButton("About...",cw);
    about_btn.setMinimumWidth(100);
    # about_btn.setFlat(True);
    about_btn.setIcon(pixmaps.purr_logo.icon());
    toplo.addWidget(about_btn);
    self._about_dialog = QMessageBox(self);
    self._about_dialog.setWindowTitle("About PURR");
    self._about_dialog.setText(self.about_message + """
        <P>PURR is not watching any directories right now. Click on the "Updated files" option to start
        watching your current directory.</P>""");
    # self._about_dialog.setStandardButtons(QMessageBox.Ok);
    self._about_dialog.setIconPixmap(pixmaps.purr_logo.pm()); 
    self.connect(about_btn,SIGNAL("clicked()"),self._about_dialog.exec_);
    cwlo.addSpacing(5);
    logframe = QFrame(cw);
    cwlo.addWidget(logframe);
    log_lo = QVBoxLayout(logframe);
    log_lo.setMargin(5);
    log_lo.setSpacing(0);
    logframe.setFrameStyle(QFrame.Box|QFrame.Raised);
#    logframe.setFrameShape(QFrame.Panel);
    logframe.setLineWidth(1);
    self.dir_label = QLabel("Directory: none",logframe);
    self.dir_label.setToolTip("""<P>This is the directory where your current purrlog is stored.
      If you want to change this, you must restart PURR with a different directory name.</P>""");
    log_lo.addWidget(self.dir_label);
    title_lo = QHBoxLayout(); log_lo.addLayout(title_lo); 
    self.title_label = QLabel("Log title: none",logframe);
    self.title_label.setToolTip("""<P>This is your current log title. To change, click on the "Rename" button.</P>""");
    title_lo.addWidget(self.title_label,1);
    self.wrename = QPushButton("Rename",logframe);
    self.wrename.setToolTip("Click to edit log title");
    self.wrename.setMinimumWidth(80);
    # self.wrename.setFlat(True);
    self.wrename.setEnabled(False);
    self.connect(self.wrename,SIGNAL("clicked()"),self._renameLogDialog);
    title_lo.addWidget(self.wrename,0);
    title_lo.addSpacing(5);
    self.wviewlog = QPushButton(pixmaps.openbook.icon(),"View",logframe);
    self.wviewlog.setToolTip("Click to see an HTML rendering of the log");
    self.wviewlog.setMinimumWidth(80);
    # self.wviewlog.setFlat(True);
    self.wviewlog.setEnabled(False);
    # log viewer dialog
    self.viewer_dialog = HTMLViewerDialog(self,config_name="log-viewer",
          buttons=[(pixmaps.blue_round_reload,"Regenerate",
                   """<P>Regenerates your log's HTML code from scratch. This can be useful if
                   your PURR version has changed, or if there was an error of some kind
                   the last time the files were generated.</P>
                   """)]);
    self._viewer_timestamp = None;
    self.connect(self.wviewlog,SIGNAL("clicked()"),self._showViewerDialog);
    self.connect(self.viewer_dialog,SIGNAL("Regenerate"),self._regenerateLog);
    title_lo.addWidget(self.wviewlog,0);
    cwlo.addSpacing(5);
    # listview of log entries
    self.etw = Kittens.widgets.ClickableTreeWidget(cw);
    cwlo.addWidget(self.etw);
    self.etw.header().setDefaultSectionSize(128);
    self.etw.header().setMovable(False);
    self.etw.setHeaderLabels(["date","entry title","comment"]);
    if hasattr(QHeaderView,'ResizeToContents'):
      self.etw.header().setResizeMode(0,QHeaderView.ResizeToContents);
    else:
      self.etw.header().setResizeMode(0,QHeaderView.Custom);
      self.etw.header().resizeSection(0,120);
    self.etw.header().setResizeMode(1,QHeaderView.Interactive);
    self.etw.header().setResizeMode(2,QHeaderView.Stretch);
    self.etw.header().show();
    try: self.etw.setAllColumnsShowFocus(True); 
    except AttributeError: pass; # Qt 4.2+
    # self.etw.setShowToolTips(True);
    self.etw.setSortingEnabled(False);
    # self.etw.setColumnAlignment(2,Qt.AlignLeft|Qt.AlignTop);
    self.etw.setSelectionMode(QTreeWidget.ExtendedSelection);
    self.etw.setRootIsDecorated(True);
    self.connect(self.etw,SIGNAL("itemSelectionChanged()"),self._entrySelectionChanged);
    self.connect(self.etw,SIGNAL("itemActivated(QTreeWidgetItem*,int)"),self._viewEntryItem);
    self.connect(self.etw,SIGNAL("itemContextMenuRequested"),self._showItemContextMenu);
    # create popup menu for data products
    self._archived_dp_menu = menu = QMenu(self);
    menu.addAction(pixmaps.editcopy.icon(),"Restore file from this entry's archived copy",self._restoreItemFromArchive);
    menu.addAction(pixmaps.editpaste.icon(),"Copy location of archived copy to clipboard",self._copyItemToClipboard);
    self._current_item = None;
    # create popup menu for entries
    self._entry_menu = menu = QMenu(self);
    menu.addAction(pixmaps.filefind.icon(),"View",self._viewEntryItem);
    menu.addAction(pixmaps.editdelete.icon(),"Delete",self._deleteSelectedEntries);
    # buttons at bottom
    cwlo.addSpacing(5);
    btnlo = QHBoxLayout(); cwlo.addLayout(btnlo); 
    self.wnewbtn = QPushButton(pixmaps.filenew.icon(),"New entry...",cw);
    self.wnewbtn.setToolTip("Click to add a new log entry");
    # self.wnewbtn.setFlat(True);
    self.wnewbtn.setEnabled(False);
    btnlo.addWidget(self.wnewbtn);
    btnlo.addSpacing(5);
    self.weditbtn = QPushButton(pixmaps.filefind.icon(),"View entry...",cw);
    self.weditbtn.setToolTip("Click to view or edit the selected log entry");
    # self.weditbtn.setFlat(True);
    self.weditbtn.setEnabled(False);
    self.connect(self.weditbtn,SIGNAL("clicked()"),self._viewEntryItem);
    btnlo.addWidget(self.weditbtn);
    btnlo.addSpacing(5);
    self.wdelbtn = QPushButton(pixmaps.editdelete.icon(),"Delete",cw);
    self.wdelbtn.setToolTip("Click to delete the selected log entry or entries");
    # self.wdelbtn.setFlat(True);
    self.wdelbtn.setEnabled(False);
    self.connect(self.wdelbtn,SIGNAL("clicked()"),self._deleteSelectedEntries);
    btnlo.addWidget(self.wdelbtn);
    # enable status line
    self.statusBar().show();
    Purr.progressMessage = self.message;
    self._prev_msg = None;
    # editor dialog for new entry
    self.new_entry_dialog = Purr.Editors.NewLogEntryDialog(self);
    self.connect(self.new_entry_dialog,SIGNAL("newLogEntry"),self._newLogEntry);
    self.connect(self.new_entry_dialog,SIGNAL("filesSelected"),self._addDPFiles);
    self.connect(self.wnewbtn,SIGNAL("clicked()"),self.new_entry_dialog.show);
    self.connect(self.new_entry_dialog,SIGNAL("shown"),self._checkPounceStatus);
    # entry viewer dialog
    self.view_entry_dialog = Purr.Editors.ExistingLogEntryDialog(self);
    self.connect(self.view_entry_dialog,SIGNAL("previous()"),self._viewPrevEntry);
    self.connect(self.view_entry_dialog,SIGNAL("next()"),self._viewNextEntry);
    self.connect(self.view_entry_dialog,SIGNAL("filesSelected"),self._addDPFilesToOldEntry);
    self.connect(self.view_entry_dialog,SIGNAL("entryChanged"),self._entryChanged);
    # saving a data product to an older entry will automatically drop it from the
    # new entry dialog
    self.connect(self.view_entry_dialog,SIGNAL("creatingDataProduct"),
                  self.new_entry_dialog.dropDataProducts);
    # resize selves
    width = Config.getint('main-window-width',512);
    height = Config.getint('main-window-height',512);
    self.resize(QSize(width,height));
    # create timer for pouncing
    self._timer = QTimer(self);
    self.connect(self._timer,SIGNAL("timeout()"),self._rescan);
    
  def resizeEvent (self,ev):
    QMainWindow.resizeEvent(self,ev);
    sz = ev.size();
    Config.set('main-window-width',sz.width());
    Config.set('main-window-height',sz.height());
    
  def closeEvent (self,ev):
    if self._hide_on_close:
      ev.ignore();
      self.hide();
      self.new_entry_dialog.hide();
    else:
      if self.purrer:
        self.purrer.detach();
      return QMainWindow.closeEvent(self,ev);
    
  def message (self,msg,ms=2000,sub=False):
    if sub:
      if self._prev_msg:
        msg = ": ".join((self._prev_msg,msg));
    else:
      self._prev_msg = msg;
    self.statusBar().showMessage(msg,ms);
    QCoreApplication.processEvents(QEventLoop.ExcludeUserInputEvents);
      
  def detachDirectory (self):
    self.purrer and self.purrer.detach();
    
  def attachDirectory (self,dirname,watchdirs=None):
    """Attaches Purr to the given directory. If watchdirs is None,
    the current directory will be watched, otherwise the given directories will be watched."""
    # check purrer stack for a Purrer already watching this directory
    dprint(1,"attaching to directory",dirname);
    for i,purrer in enumerate(self.purrer_stack):
      if os.path.samefile(purrer.dirname,dirname):
        dprint(1,"Purrer object found on stack (#%d),reusing\n",i);
        # found? move to front of stack
        self.purrer_stack.pop(i);
        self.purrer_stack.insert(0,purrer);
        # update purrer with watched directories, in case they have changed
        if watchdirs:
          purrer.watchDirectories(watchdirs);
        break;
    # no purrer found, make a new one
    else:
      dprint(1,"creating new Purrer object");
      try:
        purrer = Purr.Purrer(dirname,watchdirs or (dirname,));
      except Purr.Purrer.LockedError,err:
        # check that we could attach, display message if not
        QMessageBox.warning(self,"Catfight!","""<P><NOBR>It appears that another PURR process (%s)</NOBR>
          is already attached to <tt>%s</tt>, so we're not allowed to touch it. You should exit the other PURR
          process first.</P>"""%(err.args[0],os.path.abspath(dirname)),QMessageBox.Ok,0);
        return False;
      except Purr.Purrer.LockFailError,err:
        QMessageBox.warning(self,"Failed to lock directory","""<P><NOBR>PURR was unable to obtain a lock</NOBR>
          on directory <tt>%s</tt> (error was "%s"). The most likely cause is insufficient permissions.</P>"""%(os.path.abspath(dirname),err.args[0]),QMessageBox.Ok,0);
        return False;
      self.purrer_stack.insert(0,purrer);
      # discard end of stack
      self.purrer_stack = self.purrer_stack[:3];
      # attach signals
      self.connect(purrer,SIGNAL("disappearedFile"),
                   self.new_entry_dialog.dropDataProducts);
      self.connect(purrer,SIGNAL("disappearedFile"),
                   self.view_entry_dialog.dropDataProducts);
    # have we changed the current purrer? Update our state then
    # reopen pipe
    self.purrpipe = Purr.Pipe.open(purrer.dirname);
    if purrer is not self.purrer:
      self.message("Attached to directory %s"%purrer.dirname);
      dprint(1,"current Purrer changed, updating state");
      self.purrer = purrer;
      self.new_entry_dialog.hide();
      self.new_entry_dialog.reset();
      self.new_entry_dialog.setDefaultDirs(*purrer.watched_dirs);
      self.view_entry_dialog.setDefaultDirs(*purrer.watched_dirs);
      self.view_entry_dialog.hide();
      self._viewing_ientry = None;
      self._setEntries(self.purrer.getLogEntries());
      self._viewer_timestamp = None;
      self._updateViewer();
      self._updateNames();
      # set autopounce property from purrer. Reset _pounce to false -- this will cause
      # checkPounceStatus() into a rescan if autopounce is on.
      self.setPounceMode(purrer.autopounce);
      self._pounce = False;
      self._checkPounceStatus();
    return True;
    
  def setLogTitle (self,title):
    self.purrer.setLogTitle(title);
    self._updateNames();
    self._updateViewer();
    
  def setPounceMode (self,enable=PounceShow):
    enable = int(enable)%len(self.pounce_labels);
    if enable != self.PounceIgnore and not self.purrer:
      self.attachDirectory('.');
    self._autopounce = enable;
    if self.purrer:
      self.purrer.autopounce = enable;
    self.wpounce.setCurrentIndex(enable%len(self.pounce_labels));
    self._checkPounceStatus();
    
  def _updateNames (self):
    self.wnewbtn.setEnabled(True);
    self.wrename.setEnabled(True);
    self.wviewlog.setEnabled(True);
    self._about_dialog.setText(self.about_message + """
    <P>Your current log resides in:<PRE>  <tt>%s</tt></PRE>To see your log in all its HTML-rendered glory, point your browser to <tt>index.html</tt> therein, or use the handy "View" button provided by PURR.</P>
    
    <P>Your current working directories are:</P>
    <P>%s</P>
    """%(self.purrer.logdir,
      "".join([ "<PRE>  <tt>%s</tt></PRE>"%name for name in self.purrer.watched_dirs ])
    ));
    self.dir_label.setText("Directory: %s"%self.purrer.dirname);
    title = self.purrer.logtitle or "Unnamed log"
    self.title_label.setText("Log title: <B>%s</B>"%title);
    self.viewer_dialog.setWindowTitle(title);
    
  def _showViewerDialog (self):
    self._updateViewer(True);
    self.viewer_dialog.show();
    
  def _updateViewer (self,force=False):
    """Updates the viewer dialog.
    If dialog is not visible and force=False, does nothing.
    Otherwise, checks the mtime of the current purrer index.html file against self._viewer_timestamp.
    If it is newer, reloads it.
    """;
    if not force and not self.viewer_dialog.isVisible():
      return;
    # default text if nothing is found
    text = "<P>Nothing in the log yet. Try adding some entries first.</P>";
    try:
      mtime = os.path.getmtime(self.purrer.indexfile);
    except:
      mtime = None;
    # return if file is older than our content
    if mtime and mtime < (self._viewer_timestamp or 0):
      return;
    busy = BusyIndicator();
    try:
      text = file(self.purrer.indexfile).read();
    except:
      pass;
    self.viewer_dialog.setDocument(self.purrer.indexfile);
    self.viewer_dialog.reload();
    self.viewer_dialog.setLabel("""<P>Below is your full HTML-rendered log. Note that this window 
      is only a bare-bones viewer, not a real browser. You can't
      click on links, or do anything else besides simply look. For a fully-functional view, use your
      browser to look at the index file residing here:<BR>
      <tt>%s</tt></P> 
      """%self.purrer.indexfile);
    self._viewer_timestamp = mtime;
    
  def _setEntries (self,entries):
    self.etw.clear();
    item = None;
    for i,entry in enumerate(entries):
      item = self._addEntryItem(entry,i,item);
      
  def _renameLogDialog (self):
    (title,ok) = QInputDialog.getText(self,"PURR: Rename Log",
                  "Enter new name for this log",QLineEdit.Normal,self.purrer.logtitle);
    if ok and title != self.purrer.logtitle:
      self.setLogTitle(title);
      
  def _checkPounceStatus (self):
    pounce = self._autopounce != self.PounceIgnore or self.new_entry_dialog.isVisible();
    # rescan, if going from not-pounce to pounce
    if pounce and not self._pounce:
      self._rescan();
    self._pounce = pounce;
    # start timer -- we need it running to check the purr pipe, anyway
    self._timer.start(2000);
      
  def _forceRescan (self):
    if not self.purrer:
      self.attachDirectory('.');
    self._rescan(force=True);
    
  def _rescan (self,force=False):
    # if pounce is on, tell the Purrer to rescan directories
    if self._pounce or force:
      dps = self.purrer.rescan();
      if dps:
        filenames = [dp.filename for dp in dps];
        dprint(2,"new data products:",filenames);
        self.message("Pounced on "+", ".join(filenames));
        if self.new_entry_dialog.addDataProducts(dps) and (force or self._autopounce == self.PounceShow):
          dprint(2,"showing dialog");
          self.new_entry_dialog.show();
    # else read stuff from pipe
    if self.purrpipe:
      do_show = False;
      for command,show,content in self.purrpipe.read():
        if command == "title":
          self.new_entry_dialog.suggestTitle(content);
        elif command == "comment":
          self.new_entry_dialog.addComment(content);
        elif command == "pounce":
          self.new_entry_dialog.addDataProducts(self.purrer.makeDataProducts(
                                                [(content,not show)],unbanish=True));
        else:
          print "Unknown command received from Purr pipe: ",command;
          continue;
        do_show = do_show or show;
      if do_show:
        self.new_entry_dialog.show();
        
  def _addDPFiles (self,*files):
    """callback to add DPs corresponding to files.""";
    # quiet flag is always true
    self.new_entry_dialog.addDataProducts(self.purrer.makeDataProducts(
                          [(file,True) for file in files],unbanish=True));
    
  def _addDPFilesToOldEntry (self,*files):
    """callback to add DPs corresponding to files.""";
    # quiet flag is always true
    self.view_entry_dialog.addDataProducts(self.purrer.makeDataProducts(
                          [(file,True) for file in files],unbanish=True));
    
  def _entrySelectionChanged (self):
    selected = [ item for item in self.etw.iterator(self.etw.Iterator.Selected) if item._ientry is not None ];
    self.weditbtn.setEnabled(len(selected) == 1);
    self.wdelbtn.setEnabled(bool(selected));
      
  def _viewEntryItem (self,item=None,*dum):
    """Pops up the viewer dialog for the entry associated with the given item.
    If 'item' is None, looks for a selected item in the listview.
    The dum arguments are for connecting this to QTreeWidget signals such as doubleClicked().
    """;
    # if item not set, look for selected items in listview. Only 1 must be selected.
    select = True;
    if item is None:
      selected = [ item for item in self.etw.iterator(self.etw.Iterator.Selected) if item._ientry is not None ];
      if len(selected) != 1:
        return;
      item = selected[0];
      select = False; # already selected
    else:
      # make sure item is open -- the click will cause it to close
      self.etw.expandItem(item);
    # show dialog
    ientry = getattr(item,'_ientry',None);
    if ientry is not None:
      self._viewEntryNumber(ientry,select=select);
      
  def _viewEntryNumber (self,ientry,select=True):
    """views entry #ientry. Also selects entry in listview if select=True""";
    # pass entry to viewer dialog
    self._viewing_ientry = ientry;
    entry = self.purrer.entries[ientry];
    self.view_entry_dialog.viewEntry(entry,has_prev=(ientry>0),has_next=(ientry<len(self.purrer.entries)-1));
    self.view_entry_dialog.show();
    # select entry in listview
    if select:
      self.etw.clearSelection();
      self.etw.setItemSelected(self.etw.topLevelItem(ientry),True);
     
  def _viewPrevEntry (self):
    if self._viewing_ientry is not None and self._viewing_ientry > 0:
      self._viewEntryNumber(self._viewing_ientry-1);
    
  def _viewNextEntry (self):
    if self._viewing_ientry is not None and self._viewing_ientry < len(self.purrer.entries)-1:
      self._viewEntryNumber(self._viewing_ientry+1);
      
  def _showItemContextMenu (self,item,point,col):
    """Callback for contextMenuRequested() signal. Pops up item menu, if defined""";
    menu = getattr(item,'_menu',None);
    if menu: 
      # self._current_item tells callbacks what item the menu was referring to
      point = self.etw.mapToGlobal(point);
      self._current_item = item;
      self.etw.clearSelection();
      self.etw.setItemSelected(item,True);
      menu.exec_(point);
    else:
      self._current_item = None;
      
  def _copyItemToClipboard (self):
    """Callback for item menu.""";
    if self._current_item is None:
      return;
    dp = getattr(self._current_item,'_dp',None);
    if dp and dp.archived:
      path = dp.fullpath.replace(" ","\\ ");
      QApplication.clipboard().setText(path,QClipboard.Clipboard);
      QApplication.clipboard().setText(path,QClipboard.Selection);
      
  def _restoreItemFromArchive (self):
    """Callback for item menu.""";
    if self._current_item is None:
      return;
    dp = getattr(self._current_item,'_dp',None);
    if dp and dp.archived:
      dp.restore_from_archive(parent=self);
  
  def _deleteSelectedEntries (self):
    remaining_entries = [];
    del_entries = list(self.etw.iterator(self.etw.Iterator.Selected));
    remaining_entries = list(self.etw.iterator(self.etw.Iterator.Unselected));
    if not del_entries:
      return;
    hide_viewer = bool([ item for item in del_entries if self._viewing_ientry == item._ientry ]);
    del_entries = [ self.purrer.entries[self.etw.indexOfTopLevelItem(item)] for item in del_entries ];
    remaining_entries = [ self.purrer.entries[self.etw.indexOfTopLevelItem(item)] for item in remaining_entries ];
    # ask for confirmation
    if len(del_entries) == 1:
      msg = """<P><NOBR>Permanently delete the log entry</NOBR> "%s"?</P>"""%del_entries[0].title;
      if del_entries[0].dps:
        msg += """<P>%d data product(s) saved with this 
                  entry will be deleted as well.</P>"""%len(del_entries[0].dps);
    else:
      msg = """<P>Permanently delete the %d selected log entries?</P>"""%len(del_entries);
      ndp = 0;
      for entry in del_entries:
        ndp += len(filter(lambda dp:not dp.ignored,entry.dps));
      if ndp:
        msg += """<P>%d data product(s) saved with these entries will be deleted as well.</P>"""%ndp;
    if QMessageBox.warning(self,"Deleting log entries",msg,
          QMessageBox.Yes,QMessageBox.No) != QMessageBox.Yes:
      return;
    if hide_viewer:
      self.view_entry_dialog.hide();
    # reset entries in purrer and in our log window
    self._setEntries(remaining_entries);
    self.purrer.setLogEntries(remaining_entries);
    # log will have changed, so update the viewer
    self._updateViewer();
    # delete entry files
    for entry in del_entries:
      entry.remove_directory();

  def _addEntryItem (self,entry,number,after):
    item = entry.tw_item = QTreeWidgetItem(self.etw,after);
    item.setText(0,self._make_time_label(entry.timestamp));
    item.setText(1," "+(entry.title or ""));
    item.setToolTip(1,entry.title);
    if entry.comment:
      item.setText(2," "+entry.comment.split('\n')[0]);
      item.setToolTip(2,"<P>"+entry.comment.replace("<","&lt;").replace(">","&gt;"). \
                                    replace("\n\n","</P><P>").replace("\n","</P><P>")+"</P>");
    item._ientry = number;
    item._dp = None;
    item._menu = self._entry_menu;
    # now make subitems for DPs
    subitem = None;
    for dp in entry.dps:
      if not dp.ignored:
        subitem = self._addDPSubItem(dp,item,subitem);
    self.etw.collapseItem(item);
    return item;
    
  def _addDPSubItem (self,dp,parent,after):
    item = QTreeWidgetItem(parent,after);
    item.setText(1,dp.filename);
    item.setToolTip(1,dp.filename);
    item.setText(2,dp.comment or "");
    item.setToolTip(2,dp.comment or "");
    item._ientry = None;
    item._dp = dp;
    item._menu = self._archived_dp_menu;

  def _make_time_label (self,timestamp):
    return time.strftime("%b %d %H:%M",time.localtime(timestamp));
    
  def _newLogEntry (self,entry):
    """This is called when a new log entry is created""";
    # add entry to purrer
    self.purrer.addLogEntry(entry);
    # add entry to listview if it is not an ignored entry
    # (ignored entries only carry information about DPs to be ignored)
    if not entry.ignore:
      if self.etw.topLevelItemCount():
        lastitem = self.etw.topLevelItem(self.etw.topLevelItemCount()-1);
      else:
        lastitem = None;
      self._addEntryItem(entry,len(self.purrer.entries)-1,lastitem);
    # log will have changed, so update the viewer
    if not entry.ignore:
      self._updateViewer();
      self.show();
    
  def _entryChanged (self,entry):
    """This is called when a log entry is changed""";
    # resave the log
    self.purrer.save();
    # redo entry item
    if entry.tw_item:
      number = entry.tw_item._ientry;
      entry.tw_item = None;
      self.etw.takeTopLevelItem(number);
      if number:
	after = self.etw.topLevelItem(number-1);
      else:
	after = None;
      self._addEntryItem(entry,number,after);
    # log will have changed, so update the viewer
    self._updateViewer();
    
  def _regenerateLog (self):
    if QMessageBox.question(self.viewer_dialog,"Regenerate log","""<P><NOBR>Do you really want to regenerate the
      entire</NOBR> log? This can be a time-consuming operation.</P>""",
          QMessageBox.Yes,QMessageBox.No) != QMessageBox.Yes:
      return;
    self.purrer.save(refresh=True);
    self._updateViewer();
  