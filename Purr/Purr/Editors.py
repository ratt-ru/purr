# -*- coding: utf-8 -*-
from PyQt4.Qt import *

import time
import os
import os.path
import string

from Purr import Config,pixmaps,dprint,dprintf
import Purr.LogEntry
import Purr.Render
import Kittens.widgets
import Kittens.utils

def _makeUniqueFilename (taken_names,name):
  """Helper function. Checks if name is in the set 'taken_names'.
  If so, attepts to form up an untaken name (by adding numbered suffixes).
  Adds name to taken_names.
  """
  if name in taken_names:
    # try to form up new name
    basename,ext = os.path.splitext(name);
    num = 1;
    name = "%s-%d%s"%(basename,num,ext);
    while name in taken_names:
      num += 1;
      name = "%s-%d%s"%(basename,num,ext);
  # finally, enter name into set
  taken_names.add(name);
  return name;


_sanitize_chars = "\\:*?\"<>|";
_sanitize_trans = string.maketrans(_sanitize_chars,'_'*len(_sanitize_chars));

def _sanitizeFilename (filename):
  """Sanitizes filename for use on Windows and other brain-dead systems, by replacing a number of illegal characters
  with underscores."""
  global _sanitize_trans;
  out = filename.translate(_sanitize_trans);
  # leading dot becomes "_"
  if out[0] == '/':
    out = '_'+out[1:];
  return out;

class DPTreeWidget (Kittens.widgets.ClickableTreeWidget):
  """This class implements a QTreeWidget for data products.
  """;
  def __init__ (self,*args):
    Kittens.widgets.ClickableTreeWidget.__init__(self,*args);
    # insert columns, and numbers for them
    self.header().setDefaultSectionSize(120);
    columns = [ "action","filename","type","rename to","render","comment" ];
    self.setHeaderLabels(columns);
    self.ColAction,self.ColFilename,self.ColType,self.ColRename,self.ColRender,self.ColComment = range(len(columns));
    self.setSortingEnabled(False);
    self.setRootIsDecorated(False);
    self.setEditTriggers(QAbstractItemView.AllEditTriggers);
    # sort out resizing modes
    self.header().setMovable(False);
    self.header().setResizeMode(self.ColFilename,QHeaderView.Interactive);
    self.header().setResizeMode(self.ColType,QHeaderView.ResizeToContents);
    self.header().setResizeMode(self.ColRename,QHeaderView.Interactive);
    self.header().setResizeMode(self.ColComment,QHeaderView.Stretch);
    self.header().setResizeMode(self.ColAction,QHeaderView.Fixed);
    self.header().setResizeMode(self.ColRender,QHeaderView.Fixed);
    self.header().resizeSection(self.ColAction,64);
    self.header().resizeSection(self.ColRender,64);
    self._fontmetrics = QFontMetrics(QFont());
    # setup other properties of the listview
    self.setAcceptDrops(True);
    try: self.setAllColumnsShowFocus(True); 
    except AttributeError: pass; # qt 4.2+
    # self.setDefaultRenameAction(QTreeWidget.Accept);
    self.setSelectionMode(QTreeWidget.SingleSelection);
    self.header().show();
    self.setSizePolicy(QSizePolicy.MinimumExpanding,QSizePolicy.MinimumExpanding);
    self.connect(self,SIGNAL("mouseButtonClicked"),self._itemClicked);
    self.connect(self,SIGNAL("itemActivated(QTreeWidgetItem*,int)"),self._startOrStopEditing);
    self.connect(self,SIGNAL("itemChanged(QTreeWidgetItem*,int)"),self._itemRenamed);
    self.connect(self,SIGNAL("currentItemChanged(QTreeWidgetItem*,QTreeWidgetItem*)"),self._currentItemChanged);
    self.connect(self,SIGNAL("itemcontextMenuRequested"),self._showItemContextMenu);
    self.connect(self,SIGNAL("droppedFiles"),self,SIGNAL("filesSelected"));
    # create popup menu for existing DPs
    self._archived_dp_menu = menu = QMenu();
    menu.addAction(pixmaps.editcopy.icon(),"Restore file from this entry's archived copy",self._restoreItemFromArchive);
    menu.addAction(pixmaps.editpaste.icon(),"Copy location of archived copy to clipboard",self._copyItemToClipboard);
    # currently selected item
    self._current_item = None;
    # item onto which something was dropped
    self._dropped_on = None;
    # currently edited item and column
    self._editing = None;
    # dictionary of listview items
    # key is (path,archived) tuple, value is item
    self.dpitems = {};

    self._policy_list_default 	= ( ("copy",pixmaps.copy.icon()),
				    ("move",pixmaps.move.icon()),
				    ("ignore",pixmaps.grey_round_cross.icon()),
				    ("banish",pixmaps.red_round_cross.icon()) );
    self._policy_list_archived 	= ( ("keep",pixmaps.checkmark.icon()),
				    ("remove",pixmaps.grey_round_cross.icon()) );

  def _checkDragDropEvent (self,ev):
    """Checks if event contains a file URL, accepts if it does, ignores if it doesn't""";
    mimedata = ev.mimeData();
    if mimedata.hasUrls():
      urls = [ str(url.toLocalFile()) for url in mimedata.urls() if url.toLocalFile() ];
    else:
      urls = [];
    # accept event if drag text is a file URL
    if urls:
      ev.acceptProposedAction();
      return urls;
    else:
      ev.ignore();
      return None;
    
  def dragEnterEvent (self,ev):
    """Process drag-enter event. Use function above to accept or ignore it"""
    self._checkDragDropEvent(ev);
      
  def dragMoveEvent (self,ev):
    """Process drag-move event. Use function above to accept or ignore it"""
    self._checkDragDropEvent(ev);
      
  def dropEvent (self,ev):
    """Process drop event."""
    # use function above to accept event if it contains a file URL
    files = self._checkDragDropEvent(ev);
    if files:
      # see which item the event was dropped on
      pos = self.viewport().mapFrom(self,ev.pos());
      dropitem = self.itemAt(pos);
#      print "dropped on",pos.x(),pos.y(),dropitem, \
#        dropitem and hasattr(dropitem,'_dp') and (dropitem._dp.fullpath or dropitem._dp.sourcepath);
      # if event originated with ourselves, reorder items
      if ev.source() is self:
        self.reorderItems(dropitem,*files);
      # else event is from someone else, accept the dropped files
      else:
        self._dropped_on = dropitem;
        self.emit(SIGNAL("droppedFiles"),*files);
        # if event originated with another DPTreeWidget, emit a draggedAwayFiles() signal on its behalf
        if isinstance(ev.source(),DPTreeWidget):
          ev.source().emit(SIGNAL("draggedAwayFiles"),*files);
      
  def mimeTypes (self):
    return [ "text/x-url" ];
  
  def mimeData (self,itemlist):
    mimedata = QMimeData();
    urls = [];
    for item in itemlist:
      if item._dp:
        urls.append(QUrl.fromLocalFile(dp.fullpath or dp.sourcepath));
    mimedata.setUrls(urls);
    return mimedata;
      
  def dragObject (self):
    """Called when a drag is started. Creates a text drag object from
    selected files.""";
    
    # collect list of selected files
    filelist = [];
    for item,dp in self.getItemDPList():
      if item.isSelected():
        filelist.append('file://'+(dp.fullpath or dp.sourcepath));
    # generate drag object if list is not empty
    if filelist:
      text = "\n".join(filelist);
      dobj = QTextDrag(text,self);
      return dobj;
    else:
      return None;
    
  def clear (self):
    QTreeWidget.clear(self);
    self.dpitems = {};

  def _itemComboBox (self,item,column):
    """This returns the QComboBox associated with item and column, or creates a new one if
    it hasn't been created yet. The reason we don't create a combobox immediately is because
    the item needs to be inserted into its QTreeWidget first.""";
    if item.treeWidget() is not self:
      return None;
    combobox = self.itemWidget(item,column);
    if not combobox:
      combobox = QComboBox(self);
      # combobox.setSizeAdjustPolicy(QComboBox.AdjustToContents);
      self.setItemWidget(item,column,combobox);
      width = 0;
      for num,(name,icon) in enumerate(item._combobox_option_list[column]):
	if icon:
	  combobox.addItem(icon,name);
	else:
	  combobox.addItem(name);
	width = max(width,self._fontmetrics.width(name) + (icon and 16 or 0));
      combobox.setCurrentIndex(item._combobox_current_index[column]);
      item._combobox_changed[column] = Kittens.utils.curry(self._updateItemComboBoxIndex,item,column);
      QObject.connect(combobox,SIGNAL("currentIndexChanged(int)"),item._combobox_changed[column]);
      QObject.connect(combobox,SIGNAL("currentIndexChanged(int)"),self._emitUpdatedSignal);
      # resize section if needed
      width += 32;
      if width > self.header().sectionSize(column):
	self.header().resizeSection(column,width);
    return combobox;
	
  def _emitUpdatedSignal (self,*dum):
    self.emit(SIGNAL("updated"));

  def _updateItemComboBoxIndex (self,item,column,num):
    """Callback for comboboxes: notifies us that a combobox for the given item and column has changed""";
    item._combobox_current_index[column] = num;
    item._combobox_current_value[column] = item._combobox_option_list[column][num][0];

  def setItemPolicy (self,item,policy):
    """Sets the policy of the given item""";
    index = item._combobox_indices[self.ColAction].get(policy,0);
    self._updateItemComboBoxIndex(item,self.ColAction,index);
    combobox = self.itemWidget(item,self.ColAction);
    if combobox:
      combobox.setCurrentIndex(index);

  def getItemDPList (self):
    """Returns list of item,dp pairs corresponding to content of listview.
    Not-yet-saved items will have dp=None.""";
    itemlist = [ (item,item._dp) for item in self.iterator() ];
    return itemlist;
      
  def _makeDPItem (self,parent,dp,after=None):
    """Creates listview item for data product 'dp', inserts it after item 'after'""";
    if parent:
      item = QTreeWidgetItem(parent,after);
    else:
      item = QTreeWidgetItem();
    item.setTextAlignment(self.ColAction,Qt.AlignRight|Qt.AlignVCenter);
    item.setTextAlignment(self.ColFilename,Qt.AlignRight|Qt.AlignVCenter);
    item.setTextAlignment(self.ColType,Qt.AlignLeft|Qt.AlignVCenter);
    item.setTextAlignment(self.ColRename,Qt.AlignLeft|Qt.AlignVCenter);
    item.setTextAlignment(self.ColRender,Qt.AlignHCenter|Qt.AlignVCenter);
    item.setTextAlignment(self.ColComment,Qt.AlignLeft|Qt.AlignVCenter);
    item.setFlags(Qt.ItemIsSelectable|Qt.ItemIsDragEnabled|Qt.ItemIsDropEnabled|Qt.ItemIsEnabled);
    item._dp = dp;
    # init stuff for combobox functions above
    item._combobox_option_list = {};
    item._combobox_current_index = {};
    item._combobox_current_value = {};
    item._combobox_indices = {};
    item._combobox_changed = {};
    # setup available policies for new or archived items, set initial policy
    if dp.archived:
      item._menu = self._archived_dp_menu;
      item._combobox_option_list[self.ColAction] = policies = self._policy_list_archived;
      policy = "keep";
    else:
      item._combobox_option_list[self.ColAction] = policies = self._policy_list_default;
      policy = dp.policy;
    # create reverse mapping from policy names to indices
    item._combobox_indices[self.ColAction] = dict([ (name,num) for num,(name,icon) in enumerate(policies) ]);
    # init item policy
    self.setItemPolicy(item,policy);
    # set other columns
    basename = os.path.basename(dp.sourcepath);
    name,ext = os.path.splitext(basename);
    item.setText(self.ColFilename,name);
    item.setText(self.ColType,ext);
    item.setToolTip(self.ColFilename,basename);
    item.setToolTip(self.ColType,basename);
    item.setData(self.ColComment,Qt.EditRole,QVariant(dp.comment or ""));
    # make sure new filenames are unique
    filename = _sanitizeFilename(dp.filename);
    if not dp.archived:
      # tack on .tgz prefix onto dirs
      if os.path.isdir(dp.sourcepath) and not filename.endswith(".tgz"):
        filename += ".tgz";
      # form up set of taken names
      taken_names = set();
      for i0,dp0 in self.getItemDPList():
        if dp0.policy not in ["remove","ignore","banish"]:
          taken_names.add(str(i0.text(self.ColRename)));
      # ensure uniqueness of filename
      filename = _makeUniqueFilename(taken_names,filename);
    item.setData(self.ColRename,Qt.EditRole,QVariant(filename));
    # get list of available renderers
    item._renderers = Purr.Render.getRenderers(dp.fullpath or dp.sourcepath);
    item._render = 0;
    item._combobox_option_list[self.ColRender] = [ (name,None) for name in item._renderers ];
    # create reverse mapping from renderer names to indices
    item._combobox_indices[self.ColRender] = dict([ (name,num) for num,name in enumerate(item._renderers) ]);
    # for archived items, try to find renderer in list
    if dp.archived:
      try:
        item._render = item._renderers.index(dp.render);
      except:
        pass;
    self._updateItemComboBoxIndex(item,self.ColRender,item._render);
    # add to map of items
    self.dpitems[dp.fullpath or dp.sourcepath] = item;
    return item;
    
  def _startOrStopEditing (self,item=None,column=None):
    if self._editing:
      if self._editing == (item,column):
        return;
      else:
        item,column = self._editing;
        self.closePersistentEditor(*self._editing);
        self._editing = None;	
        if column == self.ColRename:
          item.setText(self.ColRename,_sanitizeFilename(str(item.text(self.ColRename))));
    if item and column in [self.ColRename,self.ColComment]:
      self._editing = item,column;
      dprint(2,"opening editor for",item,column);
      self.openPersistentEditor(item,column);
  
  def _itemClicked (self,button,item,point,column):
    self._startOrStopEditing(); # stop editing
    if not item or button != Qt.LeftButton:
      return;
    self._startOrStopEditing(item,column);  # start editing if editable column
  
  def _itemRenamed (self,item,col):
    self._startOrStopEditing();
    self.emit(SIGNAL("updated"));
    
  def _currentItemChanged(self,item,previous):
    self._startOrStopEditing();
  
  def _showItemContextMenu (self,item,point,col):
    """Callback for contextMenuRequested() signal. Pops up item menu, if defined""";
    menu = getattr(item,'_menu',None);
    if menu: 
      # self._current_item tells callbacks what item the menu was referring to
      self._current_item = item;
      self.clearSelection();
      self.setItemSelected(item,True);
      menu.exec_(point);
    else:
      self._current_item = None;
      
  def _copyItemToClipboard (self):
    """Callback for item menu.""";
    dp = self._current_item and getattr(self._current_item,'_dp',None);
    if dp and dp.archived:
      path = dp.fullpath.replace(" ","\\ ");
      QApplication.clipboard().setText(path,QClipboard.Clipboard);
      QApplication.clipboard().setText(path,QClipboard.Selection);
  
  def _restoreItemFromArchive (self):
    """Callback for item menu.""";
    dp = self._current_item and getattr(self._current_item,'_dp',None);
    if dp and dp.archived:
      dp.restore_from_archive(parent=self);
        
  def reorderItems(self,beforeitem,*files):
    # make list of items to be moved
    moving_items = []; 
    for file in files:
      item = self.dpitems.get(file,None);
      if item:
        moving_items.append(self.takeTopLevelItem(self.indexOfTopLevelItem(item)));
    # move them to specified location
    if beforeitem:
      index = self.indexOfTopLevelItem(beforeitem);
    else:
      index = self.topLevelItemCount();
    if moving_items:
      self.insertTopLevelItems(index,moving_items);
    
  def fillDataProducts(self,dps):
    """Fills listview with existing data products""";
    item = None;
    for dp in dps:
      if not dp.ignored:
        item = self._makeDPItem(self,dp,item);
	# ensure combobox widgets are made
	self._itemComboBox(item,self.ColAction);
	self._itemComboBox(item,self.ColRender);
      
  def addDataProducts(self,dps):
    """Adds new data products to listview. dps is a list of DP objects.
    Returns True if new (non-quiet) DPs are added, or if existing non-quiet dps are updated.
    (this usually tells the main window to wake up)
    """;
    busy = Purr.BusyIndicator();
    wakeup = False;
    # build up list of items to be inserted
    itemlist = [];
    for dp in dps:
      item = self.dpitems.get(dp.sourcepath);
      # if item already exists, it needs to be moved to its new position
      if item:
        itemlist.append(self.takeTopLevelItem(self.indexOfTopLevelItem(item)));
      # else make a new item object
      else:
        itemlist.append(self._makeDPItem(None,dp));
      wakeup = wakeup or not (dp.ignored or dp.quiet);
    # if these DPs were added as a result of a drag-and-drop, we need to insert them in FRONT of the dropped-on item
    if self._dropped_on:
      index = self.indexOfTopLevelItem(self._dropped_on);
    # else insert at end (after=None)
    else:
      index = self.topLevelItemCount();
    if itemlist:
      self.insertTopLevelItems(index,itemlist);
      self.emit(SIGNAL("updated"));
    for item in itemlist:
      # ensure combobox widgets are made
      self._itemComboBox(item,self.ColAction);
      self._itemComboBox(item,self.ColRender);
    return wakeup;
  
  def dropDataProducts (self,*pathnames):
    """Drops (that is, deletes) new (i.e. non-archived) DP items matching the given pathnames.""";
    trash = QTreeWidget(None);
    updated = False;
    for path in pathnames:
      item = self.dpitems.get(path);
      if item and not item._dp.archived:
        self.takeTopLevelItem(self.indexOfTopLevelItem(item));
        trash.addTopLevelItem(item);
        del self.dpitems[path];
        updated = True;
    if updated:
      self.emit(SIGNAL("updated"));
        
  def resolveFilenameConflicts (self):
    """Goes through list of DPs to make sure that their destination names
    do not clash. Adjust names as needed. Returns True if some conflicts were resolved.
    """
    taken_names = set();
    resolved = False;
    # iterate through items
    for item,dp in self.getItemDPList():
      # only apply this to saved DPs
      if dp.policy not in ["remove","ignore","banish"]:
        name0 = str(item.text(self.ColRename));
        name = _makeUniqueFilename(taken_names,name0);
        if name != name0:
          item.setText(self.ColRename,name);
          resolved = True;
          self.emit(SIGNAL("updated"));
    return resolved;
       
  def buildDPList (self):
    """Builds list of data products."""
    dps = [];
    itemlist = self.getItemDPList();
    # first remove all items marked for removal, in case their names clash with new or renamed items
    for item,dp in itemlist:
      item._policy = item._combobox_current_value[self.ColAction];
      if dp and item._policy == "remove":
        dp.remove_file();
        dp.remove_subproducts();
    # now, make list
    for item,dp in itemlist:
      if item._policy == "remove":
        continue;
      # update rendered and comment
      dp.render  = item._combobox_current_value[self.ColRender];
      dp.comment = str(item.text(self.ColComment));
      # archived DPs may need to be renamed, for new ones simply set the name
      if dp.archived:
        dp.rename(str(item.text(self.ColRename)));
      else:
        dp.set_policy(item._policy);
        dp.filename = str(item.text(self.ColRename));
      dps.append(dp);
    return dps;
      
class LogEntryEditor (QWidget):
  """This class provides a widget for editing log entries.
  """;
  def __init__ (self,parent):
    QWidget.__init__(self,parent);
    # create splitter
    lo = QVBoxLayout(self);
    lo.setMargin(0);
    self.wsplitter = QSplitter(self);
    self.wsplitter.setOrientation(Qt.Vertical);
    self.wsplitter.setChildrenCollapsible(False);
    # self.wsplitter.setFrameStyle(QFrame.Box|QFrame.Raised);
    # self.wsplitter.setMargin(0);
    self.wsplitter.setLineWidth(0);
    lo.addWidget(self.wsplitter);
    # create pane for comment editor
    editorpane = QWidget(self.wsplitter);
    lo_top = QVBoxLayout(editorpane);
    # lo_top.setResizeMode(QLayout.Minimum);
    lo_top.setMargin(0);
    # create comment editor
    # create title and timestamp label, hide timestamp until it is set (below)
    lo_topline = QHBoxLayout(); lo_top.addLayout(lo_topline);
    lo_topline.setMargin(0);
    self.wtoplabel = QLabel("Entry title:",editorpane);
    self.wtimestamp = QLabel("",editorpane);
    lo_topline.addWidget(self.wtoplabel);
    lo_topline.addStretch(1);
    lo_topline.addWidget(self.wtimestamp);
    # add title editor
    self.wtitle   = QLineEdit(editorpane);
    lo_top.addWidget(self.wtitle); 
    self.connect(self.wtitle,SIGNAL("textChanged(const QString&)"),self._titleChanged);
    # add comment editor
    # lo_top.addSpacing(5);
    lo_top.addWidget(QLabel("Comments:",editorpane));
    self.wcomment = QTextEdit(editorpane);
    self.wcomment.setSizePolicy(QSizePolicy.Expanding,QSizePolicy.Expanding);
    self.comment_doc = QTextDocument(self);
    self.wcomment.setDocument(self.comment_doc);
    self.wcomment.setAcceptRichText(False);
    self.wcomment.setLineWrapMode(QTextEdit.WidgetWidth);
    self.connect(self.comment_doc,SIGNAL("contentsChanged()"),self._commentChanged);
    lo_top.addWidget(self.wcomment);
    # generate frame for the "Data products" listview
    # lo_top.addSpacing(5);
    # create pane for comment editor
    dppane = QWidget(self.wsplitter);
    lo_top = QVBoxLayout(dppane);
    # lo_top.setResizeMode(QLayout.Minimum);
    lo_top.setMargin(0);
    dpline = QWidget(dppane);
    lo_top.addWidget(dpline);
    dpline.setSizePolicy(QSizePolicy.MinimumExpanding,QSizePolicy.Fixed);
    lo_dpline = QHBoxLayout(dpline);
    lo_dpline.setMargin(0);
    label = QLabel("<nobr>Data products (<u><font color=blue>help</font></u>):</nobr>",dpline)
    label.setToolTip(self.data_product_help);
    lo_dpline.addWidget(label);
    lo_dpline.addStretch(1);
    wnewdp = QPushButton(pixmaps.folder_open.icon(),"Add file...",dpline);
    self.connect(wnewdp,SIGNAL("clicked()"),self._showAddFileDialog);
    wnewdp_dir = QPushButton(pixmaps.folder_open.icon(),"Add dir...",dpline);
    self.connect(wnewdp_dir,SIGNAL("clicked()"),self._showAddDirDialog);
    self._add_dp_dialog = None;
    lo_dpline.addWidget(wnewdp);
    lo_dpline.addWidget(wnewdp_dir);
    # create DP listview
    ndplv = self.wdplv = DPTreeWidget(dppane);
    ndplv.setSizePolicy(QSizePolicy.Expanding,QSizePolicy.Expanding);
    lo_top.addWidget(self.wdplv);
    # connect its signals
    QObject.connect(self.wdplv,SIGNAL("updated"),self.setUpdated);
    QObject.connect(self.wdplv,SIGNAL("droppedFiles"),self,SIGNAL("filesSelected"));
    QObject.connect(self.wdplv,SIGNAL("draggedAwayFiles"),self,SIGNAL("draggedAwayFiles"));
    # other internal init
    self.reset();
    
  data_product_help = \
      """<P><I>Data products</I> are files that will be archived along with this log entry. If "pounce" 
      is enabled, PURR will watch your directories for new or updated files, and insert them in this list
      automatically. You can also click on "Add..." to add files by hand.</P>
      
      <P>Click on the <I>action</I> column to select what to do with a file. Click on the <I>rename</I> column 
      to archive the file under a different name. Click on the <I>comment</I> column to enter a comment for the file. Click on the <I>render</I> column to select a rendering for the file. The basic rendering is "link", which makes a simple HTML link to the archived file. Certain file types (e.g. images) may support
      more elaborate renderings.</P>
      
      <P>The meaning of the different actions is:</P>
      <DL>
      <DT><B>copy</B></DT><DD>data product will be copied to the log.</DD>
      <DT><B>move</B></DT><DD>data product will be moved to the log.</DD>
      <DT><B>ignore</B></DT><DD>data product will not appear in the log, however PURR will keep
      watching it, and will pounce on it if it changes again.</DD>
      <DT><B>banish</B></DT><DD>data product will not appear in the log, and PURR will stop
      watching it (you can un-banish a data product later by adding it via the 
      "Add..." button.)</DD>
      <DT><B>keep</B></DT><DD>(for existing products only) retain data product with this log entry.</DD>
      <DT><B>remove</B></DT><DD>(for existing products only) remove data product from this log entry.</DD>
      </DL>
      """;
      
  def hideEvent (self,event):
    QWidget.hideEvent(self,event);
    if self._add_dp_dialog:
      self._add_dp_dialog.hide();
    
  def resetDPs (self):
    self.wdplv.clear();
    
  def reset (self):
    self.wdplv.clear();
    self.entry = self._timestamp = None;
    self.wtimestamp.hide();
    self.setEntryTitle("Untitled entry");
    self.setEntryComment("No comment");
    self._default_dir = ".";
    # _title_changed is True if title was changed or edited manually
    # _comment_changed is True if comment was changed or edited manually
    # _commend_edited is True if comment was eddited since the last time something was
    #   added with addComment()
    self._title_changed = self._comment_changed = self._comment_edited = False;
    # _last_auto_comment is the last comment to have been added via addComment()
    self._last_auto_comment = None;
    self.updated = False;
    
  def setUpdated (self,updated=True):
    self.updated = updated;
    if updated:
      self.emit(SIGNAL("updated"));
    
  def setDefaultDirs (self,*dirnames):
    self._default_dirs = dirnames;
    
  class AddDataProductDialog (QFileDialog):
    """This is a file selection dialog with an extra quick-jump combobox for 
    multiple directories""";
    def __init__ (self,parent,directories=False):
      QFileDialog.__init__(self);
      self.setWindowTitle("PURR: Add Data Products");
      self.dirlist = None;
      # add filters
      #self._dirfilter = "Any directories (*)";
      #if hasattr(self,'setNameFilters'):  # qt4.4+
      #  self.setNameFilters(["Any files (*)",self._dirfilter]);
      #else:
      #  self.setFilters(["Any files (*)",self._dirfilter]);
      # connect signals (translates into a SIGNAL with string arguments)
      self.connect(self,SIGNAL("filesSelected(const QStringList&)"),self._filesSelected);
      self.connect(self,SIGNAL("fileSelected(const QString&)"),self._fileSelected);
      self.connect(self,SIGNAL("currentChanged(const QString&)"),self._fileHighlighted);
      # self.connect(self,SIGNAL("filterSelected(const QString&)"),self._filterSelected);
      # resize selves
      self.config_name = "add-file-dialog";
      width = Config.getint('%s-width'%self.config_name,768);
      height = Config.getint('%s-height'%self.config_name,512);
      self.resize(QSize(width,height));
      
    def resizeEvent (self,ev):
      QFileDialog.resizeEvent(self,ev);
      sz = ev.size();
      Config.set('%s-width'%self.config_name,sz.width());
      Config.set('%s-height'%self.config_name,sz.height());
      
    def show (self):
      QFileDialog.show(self);
      self._file = None;
      
#    def done (self,code):
#      """Workaround for QFileDialog bug: if DirctoryOnly mode, it doesn't actually emit any
#      fileSelected() when OK is pressed. So we catch the selected dir via fileHighlighted() 
#      below, and report it here.""";
#      if code == 1 and self.mode() == QFileDialog.DirectoryOnly and self._file:
#        self.emit(SIGNAL("filesSelected"),self._file);
#      QFileDialog.done(self,code);
      
    def _filterSelected (self,file_filter):
      if str(file_filter) == self._dirfilter:
        self.setFileMode(QFileDialog.Directory);
        self.setOption(QFileDialog.ShowDirsOnly);
      else:
        self.setFileMode(QFileDialog.ExistingFiles);
        self.setOption(0);
    
    def setDirList (self,dirlist):
      if dirlist is not self.dirlist:
        self.dirlist = dirlist;
        if dirlist and hasattr(self,'setSidebarUrls'):
          self.setSidebarUrls([QUrl.fromLocalFile(path) for path in dirlist]);
          
    def _filesSelected (self,filelist):
      self.emit(SIGNAL("filesSelected"),*map(str,filelist));
      
    def _fileSelected (self,file):
      self.emit(SIGNAL("filesSelected"),str(file));
      
    def _fileHighlighted (self,file):
      self._file = str(file);
  
  def _showAddFileDialog (self,add_dir=False):
    # create dialog when first called
    dialog = self._add_dp_dialog;
    if not dialog:
      self._add_dp_dialog = dialog = self.AddDataProductDialog(self);
      self.connect(dialog,SIGNAL("filesSelected"),self,SIGNAL("filesSelected"));
    # set mode
    if add_dir:
      dialog.setFileMode(QFileDialog.Directory);
    else:
      dialog.setFileMode(QFileDialog.ExistingFiles);
    # add quick-jump combobox
    dialog.setDirList(self._default_dirs);
    dialog.setDirectory(dialog.directory()); # hope this is the same as rereadDir() in qt3
    dialog.show();
    dialog.raise_();
    
  def _showAddDirDialog (self):
    return self._showAddFileDialog(add_dir=True);
  
  def _titleChanged (self,*dum):
    self._title_changed = True;
    self.setUpdated();
    
  def _commentChanged (self,*dum):
    self._comment_changed = self._comment_edited = True;
    self.setUpdated();
  
  def suggestTitle (self,title):
    """Suggests a title for the entry.
    If title has been manually edited, suggestion is ignored.""";
    if not self._title_changed or not str(self.wtitle.text()):
      self.wtitle.setText(title);
      self._title_changed = False;
    
  def addComment (self,comment):
    # get current comment text, if nothing was changed at all, use empty text
    if self._comment_changed:
      cur_comment = str(self.comment_doc.toPlainText());
      cpos = self.wcomment.textCursor();
    else:
      cur_comment = "";
      cpos = None;
    # no current comments? Replace
    if not cur_comment:
      cur_comment = comment;
    # else does the comment still end with the last auto-added string? Simply
    # append our comment then
    elif self._last_auto_comment and cur_comment.endswith(self._last_auto_comment):
      cur_comment += comment;
    # else user must've edited the end of the comment. Start a new paragraph and append our
    # comment
    else:
      cur_comment += "\n\n"+comment;
    self._comment_edited = False;
    self._last_auto_comment = comment;
    # update widget
    self.comment_doc.setPlainText(cur_comment);
    if cpos:
      self.wcomment.setTextCursor(cpos);
    
  def countRemovedDataProducts (self):
    """Returns number of DPs marked for removal""";
    return len([item for item,dp in self.wdplv.getItemDPList() if dp.policy == "remove"]);
      
  def resolveFilenameConflicts (self,dialog=True):
    """Goes through list of DPs to make sure that their destination names
    do not clash. Applies new names. Returns True if some conflicts were resolved.
    If dialog is True, shows confirrmation dialog."""
    resolved = self.wdplv.resolveFilenameConflicts();
    if resolved and dialog:
      QMessageBox.warning(self,"Filename conflicts","""<P>
        <NOBR>PURR has found duplicate destination filenames among your data products.</NOBR> 
        This is not allowed, so some filenames have been adjusted to avoid name clashes.
        Please review the changes before saving this entry.
        </P>""",
        QMessageBox.Ok,0);
    return resolved;
    
  def updateEntry (self):
    """Updates entry object with current content of dialog. 
    In new entry mode (setEntry() not called, so self.entry=None), creates new entry object.
    In old entry mode (setEntry() called), updates and saves old entry object.
    """;
    # form up new entry
    title = str(self.wtitle.text());
    comment = str(self.comment_doc.toPlainText());
    # process comment string -- eliminate single newlines, make double-newlines separate paragraphs
    comment = "\n".join([ pars.replace("\n"," ") for pars in comment.split("\n\n") ]);
    # go through data products and decide what to do with each one
    busy = Purr.BusyIndicator();
    # get list of DPs
    dps = self.wdplv.buildDPList();
    # emit signal for all newly-created DPs
    for dp in dps:
      if not dp.archived:
        self.emit(SIGNAL("creatingDataProduct"),dp.sourcepath);
    # update or return new entry
    if self.entry:
      self.entry.update(title=title,comment=comment,dps=dps);
      self.entry.save();
      return self.entry;
    else:
      return Purr.LogEntry(time.time(),title,comment,dps);
    
  def updateIgnoredEntry (self):
    """Updates an ignore-entry object with current content of dialog, by
    marking all data products for ignore."""
    # collect new DPs from items 
    dps = [];
    for item,dp in self.wdplv.getItemDPList():
      if dp and not dp.archived: # None means a new DP
        # set all policies to ignore, unless already set to banish
        if dp.policy != "banish":
          self.wdplv.setItemPolicy(item,"ignore");
          dp.set_policy("ignore");
        dps.append(dp);
    # return new entry
    return Purr.LogEntry(time.time(),dps=dps,ignore=True);
    
  def setEntry (self,entry=None):
    """Populates the dialog with contents of an existing entry.""";
    busy = Purr.BusyIndicator();
    self.entry = entry;
    self.setEntryTitle(entry.title);
    self.setEntryComment(entry.comment.replace("\n","\n\n"));
    self.wdplv.clear();
    self.wdplv.fillDataProducts(entry.dps);
    self.setTimestamp(entry.timestamp);
    self.updated = False;
  
  def addDataProducts(self,dps):
    """Adds data products to dialog.
      dps is a list of DP objects
    """;
    return self.wdplv.addDataProducts(dps);
  
  def dropDataProducts (self,*pathnames):
    """Drops new (i.e. non-archived) DP items matching the given pathnames.""";
    return self.wdplv.dropDataProducts(*pathnames);
  
  def entryTitle (self):
    return self.wtitle.text();
  
  def setEntryTitle (self,title,select=True):
    self.wtitle.setText(title);
    if select:
      self.wtitle.selectAll();
      
  def setEntryComment (self,comment,select=True):
    self.comment_doc.setPlainText(comment);
    if select:
      self.wcomment.selectAll();
    
  def setTimestamp (self,timestamp):
    self._timestamp = timestamp;
    txt = time.strftime("%x %X",time.localtime(timestamp));
    self.wtimestamp.setText(txt);
    self.wtimestamp.show();
      

class NewLogEntryDialog (QDialog):
  #class DialogTip (QToolTip):
    #def __init__ (self,parent):
      #QToolTip.__init__(self,parent);
      #self.parent = parent;
    #def maybeTip (self,pos):
      #parent = self.parent;
      #if parent._has_tip:
        #rect = QRect(pos.x()-20,pos.y()-20,40,40);
        #self.tip(rect,parent._has_tip);
        #parent._has_tip = None;
  
  def __init__ (self,parent,*args):
    QDialog.__init__(self,parent,*args);
    self.setWindowTitle("Adding Log Entry");
    self.setWindowIcon(pixmaps.purr_logo.icon());
    self.setModal(False);
    ## create pop-up tip
    #self._has_tip = None;
    #self._dialog_tip = self.DialogTip(self);
    # create editor
    lo = QVBoxLayout(self);
    lo.setMargin(5);
    # lo.setResizeMode(QLayout.Minimum);
    self.editor = LogEntryEditor(self);
    self.dropDataProducts = self.editor.dropDataProducts;
    self.connect(self.editor,SIGNAL("filesSelected"),self,SIGNAL("filesSelected"));
    # connect draggedAwayFiles() signal so that files dragged away are removed from
    # the list
    self.connect(self.editor,SIGNAL("draggedAwayFiles"),self.editor.dropDataProducts);
    lo.addWidget(self.editor);
    lo.addSpacing(5);
    # create button bar
    btnfr = QFrame(self);
    btnfr.setSizePolicy(QSizePolicy.MinimumExpanding,QSizePolicy.Fixed);
    # btnfr.setMargin(5);
    lo.addWidget(btnfr);
    lo.addSpacing(5);
    btnfr_lo = QHBoxLayout(btnfr);
    btnfr_lo.setMargin(0);
    newbtn = QPushButton(pixmaps.filesave.icon(),"Add new entry",btnfr);
    newbtn.setToolTip("""<P>Saves new log entry, along with any data products not marked
      as "ignore" or "banish".<P>""");
    self.ignorebtn = QPushButton(pixmaps.red_round_cross.icon(),"Ignore all",btnfr);
    self.ignorebtn.setEnabled(False);
    self.ignorebtn.setToolTip("""<P>Tells PURR to ignore all listed data products. PURR
      will not pounce on these files again until they have been modified.<P>""");
    cancelbtn = QPushButton(pixmaps.grey_round_cross.icon(),"Hide",btnfr);
    cancelbtn.setToolTip("""<P>Hides this dialog.<P>""");
    QObject.connect(newbtn,SIGNAL("clicked()"),self.addNewEntry);
    QObject.connect(self.ignorebtn,SIGNAL("clicked()"),self.ignoreAllDataProducts);
    QObject.connect(cancelbtn,SIGNAL("clicked()"),self.hide);
    btnfr_lo.setMargin(0);
    btnfr_lo.addWidget(newbtn,2);
    btnfr_lo.addStretch(1);
    btnfr_lo.addWidget(self.ignorebtn,2);
    btnfr_lo.addStretch(1);
    btnfr_lo.addWidget(cancelbtn,2);
    self.setSizePolicy(QSizePolicy.MinimumExpanding,QSizePolicy.MinimumExpanding);
    # resize selves
    self.setMinimumSize(256,512);
    width = Config.getint('entry-editor-width',512);
    height = Config.getint('entry-editor-height',512);
    self.resize(QSize(width,height));
    
  def resizeEvent (self,ev):
    QDialog.resizeEvent(self,ev);
    sz = ev.size();
    Config.set('entry-editor-width',sz.width());
    Config.set('entry-editor-height',sz.height());
  
  def showEvent (self,ev):
    QDialog.showEvent(self,ev);
    self.emit(SIGNAL("shown"),True);
    
  def hideEvent (self,ev):
    QDialog.hideEvent(self,ev);
    self.emit(SIGNAL("shown"),False);

  def reset (self):
    self.editor.reset();
    
  def addDataProducts (self,dps):
    updated = self.editor.addDataProducts(dps);
    self.ignorebtn.setEnabled(True);
    return updated;
  
  def suggestTitle(self,title):
    self.editor.suggestTitle(title);
    
  def addComment(self,comment):
    self.editor.addComment(comment);
    
  def setDefaultDirs (self,*dirs):
    self.editor.setDefaultDirs(*dirs);
    
  def ignoreAllDataProducts (self):
    # confirm with user
    if QMessageBox.question(self,"Ignoring all data products","""<P><NOBR>Do you really
          want to ignore all data products</NOBR> listed here? PURR will ignore these
          files until they have been modified again.""",
          QMessageBox.Yes,QMessageBox.No) != QMessageBox.Yes:
      return;
    # add ingore entry, which will store info on all ignored data products
    entry = self.editor.updateIgnoredEntry();
    self.emit(SIGNAL("newLogEntry"),entry);
    self.editor.resetDPs();
    self.hide();
    
  def addNewEntry (self):
    # if some naming conflicts have been resolved, return -- user will need to re-save
    if self.editor.resolveFilenameConflicts():
      return;
    # confirm with user
    if QMessageBox.question(self,"Adding new entry","""<P><NOBR>Do you really want to add
          a new log entry</NOBR> titled "%s"?"""%(self.editor.entryTitle()),
          QMessageBox.Yes,QMessageBox.No) != QMessageBox.Yes:
      return;
    # add entry
    entry = self.editor.updateEntry();
    self.emit(SIGNAL("newLogEntry"),entry);
    self.editor.reset();
    self.hide();
    
class ExistingLogEntryDialog (QDialog):
  def __init__ (self,parent,*args):
    QDialog.__init__(self,parent,*args);
    self.setModal(False);
    # make stack for viewer and editor components
    lo = QVBoxLayout(self);
    lo.setMargin(5);
    self.wstack = QStackedWidget(self);
    lo.addWidget(self.wstack);
    self.wstack.setSizePolicy(QSizePolicy.Expanding,QSizePolicy.Expanding);
    # make editor panel
    self.editor_panel = QWidget(self.wstack);
    self.editor_panel.setSizePolicy(QSizePolicy.Expanding,QSizePolicy.Expanding);
    self.wstack.addWidget(self.editor_panel);
    lo = QVBoxLayout(self.editor_panel);
    lo.setMargin(0);
    # create editor
    self.editor = LogEntryEditor(self.editor_panel);
    self.connect(self.editor,SIGNAL("updated"),self._entryUpdated);
    self.connect(self.editor,SIGNAL("filesSelected"),self,SIGNAL("filesSelected"));
    self.connect(self.editor,SIGNAL("creatingDataProduct"),
                 self,SIGNAL("creatingDataProduct"));
    lo.addWidget(self.editor);
    self.dropDataProducts = self.editor.dropDataProducts;
    # create button bar for editor
    btnfr = QFrame(self.editor_panel);
    btnfr.setSizePolicy(QSizePolicy.MinimumExpanding,QSizePolicy.Fixed);
    # btnfr.setMargin(5);
    lo.addWidget(btnfr);
    lo.addSpacing(5);
    btnfr_lo = QHBoxLayout(btnfr);
    self.wsave = QPushButton(pixmaps.filesave.icon(),"Save",btnfr);
    QObject.connect(self.wsave,SIGNAL("clicked()"),self._saveEntry);
    cancelbtn = QPushButton(pixmaps.grey_round_cross.icon(),"Cancel",btnfr);
    QObject.connect(cancelbtn,SIGNAL("clicked()"),self._cancelEntry);
    btnfr_lo.setMargin(0);
    btnfr_lo.addWidget(self.wsave,1);
    btnfr_lo.addStretch(1);
    btnfr_lo.addWidget(cancelbtn,1);
    
    # create viewer panel
    self.viewer_panel = QWidget(self.wstack);
    self.viewer_panel.setSizePolicy(QSizePolicy.Expanding,QSizePolicy.Expanding);
    self.wstack.addWidget(self.viewer_panel);
    lo = QVBoxLayout(self.viewer_panel);
    lo.setMargin(0);
    label = QLabel("""<P>Below is an HTML rendering of your log entry. Note that this window 
      is only a bare-bones viewer, not a real browser. You can't click on links! To get access
      to this entry's data products, click the Edit button below.
      </P>""",self.viewer_panel);
    label.setWordWrap(True);
    label.setMargin(5);
    lo.addWidget(label);
    self.viewer = QTextBrowser(self.viewer_panel);
    self.viewer.setSizePolicy(QSizePolicy.Expanding,QSizePolicy.Expanding);
    self._viewer_source = None;
    QObject.connect(self.viewer,SIGNAL("anchorClicked(const QUrl &)"),self._resetSource);
    lo.addWidget(self.viewer);
    lo.addSpacing(5);
    # create button bar
    btnfr = QFrame(self.viewer_panel);
    btnfr.setSizePolicy(QSizePolicy.MinimumExpanding,QSizePolicy.Fixed);
    # btnfr.setMargin(5);
    lo.addWidget(btnfr);
    lo.addSpacing(5);
    btnfr_lo = QHBoxLayout(btnfr);
    btnfr_lo.setMargin(0);
    btn = self.wprev = QPushButton(pixmaps.previous.icon(),"Previous",btnfr);
    QObject.connect(btn,SIGNAL("clicked()"),self,SIGNAL("previous()"));
    btnfr_lo.addWidget(btn,1);
    btnfr_lo.addSpacing(5);
    btn = self.wnext = QPushButton(pixmaps.next.icon(),"Next",btnfr);
    QObject.connect(btn,SIGNAL("clicked()"),self,SIGNAL("next()"));
    btnfr_lo.addWidget(btn,1);
    btnfr_lo.addSpacing(5);
    btn = self.wedit = QPushButton(pixmaps.edit.icon(),"Edit",btnfr);
    QObject.connect(btn,SIGNAL("clicked()"),self._editEntry);
    btnfr_lo.addWidget(btn,1);
    btnfr_lo.addStretch(1)
    btn = self.wclose = QPushButton(pixmaps.grey_round_cross.icon(),"Close",btnfr);
    QObject.connect(btn,SIGNAL("clicked()"),self.hide);
    btnfr_lo.addWidget(btn,1);
    
    # resize selves
    width = Config.getint('entry-viewer-width',512);
    height = Config.getint('entry-viewer-height',512);
    self.resize(QSize(width,height));
    # other init
    self.entry = None;
    self.updated = False;
    
  def resizeEvent (self,ev):
    QDialog.resizeEvent(self,ev);
    sz = ev.size();
    Config.set('entry-viewer-width',sz.width());
    Config.set('entry-viewer-height',sz.height());
    
  def viewEntry (self,entry,has_prev=True,has_next=True):
    # if editing previous entry, ask for confirmation
    if self.updated:
      self.show();
      self._saveEntry();
    busy = Purr.BusyIndicator();
    self.entry = entry;
    self.updated = False;
    self.setWindowTitle(entry.title);
    self._viewer_source = QUrl.fromLocalFile(self.entry.index_file);
    self.viewer.setSource(self._viewer_source);
    self.viewer.reload();
    self.wprev.setEnabled(has_prev);
    self.wnext.setEnabled(has_next);
    self.wstack.setCurrentWidget(self.viewer_panel);
    
  def _resetSource (self,*dum):
    if self._viewer_source:
      self.viewer.setSource(self._viewer_source);
    
  def setDefaultDirs (self,*dirs):
    self.editor.setDefaultDirs(*dirs);
    
  def addDataProducts (self,dps):
    self.editor.addDataProducts(dps);
    self._entryUpdated();
    
  def _editEntry (self):
    self.setWindowTitle("Editing entry");
    self.editor.setEntry(self.entry);
    self.updated = False;
    self.wsave.setEnabled(False);
    self.wstack.setCurrentWidget(self.editor_panel);

  def _saveEntry (self):
    # if some naming conflicts have been resolved, return -- user will need to re-save
    if self.editor.resolveFilenameConflicts():
      return;
    # ask for confirmation
    nremove = self.editor.countRemovedDataProducts();
    msg = "<P><nobr>Save changes to this log entry?</nobr></P>";
    if nremove:
      msg += "<P>%d archived data product(s) will be removed.</P>"%nremove;
    if QMessageBox.question(self,"Saving entry",msg,
          QMessageBox.Yes,QMessageBox.No) != QMessageBox.Yes:
      return;
    busy = Purr.BusyIndicator();
    self.editor.updateEntry();
    self.updated = False;
    self.setWindowTitle(self.entry.title);
    self.viewer.reload(); # setSource(QUrl.fromLocalFile(self.entry.index_file));
    self.wstack.setCurrentWidget(self.viewer_panel);
    # emit signal to regenerate log
    self.emit(SIGNAL("entryChanged"),self.entry);
    
  def _cancelEntry (self):
    if self.updated and QMessageBox.question(self,"Abandoning changes",
          "Abandon changes to this log entry?",
          QMessageBox.Yes,QMessageBox.No) != QMessageBox.Yes:
      return;
    self.setWindowTitle(self.entry.title);
    self.wstack.setCurrentWidget(self.viewer_panel);
    
  def _entryUpdated (self):
    self.updated = True;
    self.wsave.setEnabled(True);
    
