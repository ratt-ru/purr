import os.path
import os
import traceback

import Purr
from Purr import dprint,dprintf,verbosity
import Purr.Render
from Purr.Render import quote_url

from PyQt4.Qt import *


FULLINDEX = "fullindex.html";
INDEX = "index.html";

PURR_ICONS =  { 16:"purr16.png", 24:"purr24.png",32:"purr32.png" };

def initIndexDir (logdir):
  for sz,filename in PURR_ICONS.iteritems():
    path = os.path.join(logdir, filename);
    if not os.path.exists(path):
      Purr.pixmaps.purr_logo.pm().scaled(QSize(sz,sz),Qt.KeepAspectRatioByExpanding,Qt.SmoothTransformation).save(path);

def renderIcon (size,path=None):
  filename = PURR_ICONS[size];
  if path:
    filename = os.path.join(path,filename);
  return """<IMG SRC="%s"></IMG>"""%quote_url(filename);

def writeLogIndex (logdir,title,timestamp,entries,refresh=0):
  fullindex = os.path.join(logdir, FULLINDEX);
  tocindex = os.path.join(logdir, INDEX);

  # if 5 entries or less, do an index only, and remove the fullindex
  if len(entries) <= 5:
    if os.path.exists(fullindex):
      try:
        os.remove(fullindex);
      except:
        print "Error removing %s:"%fullindex;
        traceback.print_exc();
    fullindex = tocindex;
    tocindex = None;

  # generate TOC index, if asked to
  if tocindex:
    fobj = file(tocindex, "wt");
    # write index.html
    fobj.write("""<HTML><BODY>\n
      <TITLE>%s</TITLE>

      <H1><A CLASS="TITLE" TIMESTAMP=%d>%s</A></H1>

      """%(title,timestamp,title));
    fobj.write("""<DIV ALIGN=right><P><A HREF=%s>Printable version (single HTML page).</A></P></DIV>"""%FULLINDEX);
    # write entries
    for i,entry in enumerate(entries):
      fobj.write("""<P><A HREF="%s">%d. %s</A></P>"""%(quote_url(entry.index_file),i+1, entry.title));
    # write footer
    fobj.write("<HR>\n");
    fobj.write("""<DIV ALIGN=right>%s <I><SMALL>This log was generated
               by PURR version %s.</SMALL></I></DIV>\n"""%(renderIcon(16),Purr.Version));
    fobj.write("</BODY></HTML>\n");
    fobj = None;

  # generate full index, if asked to
  if fullindex:
    fobj = file(fullindex, "wt");
    # write index.html
    fobj.write("""<HTML><BODY>\n
      <TITLE>%s</TITLE>

      <H1><A CLASS="TITLE" TIMESTAMP=%d>%s</A></H1>

      """%(title,timestamp,title));
    # write entries
    for entry in entries:
      fobj.write(entry.renderIndex(os.path.join(os.path.basename(entry.pathname),""),refresh=refresh));
    # write footer
    fobj.write("<HR>\n");
    fobj.write("""<DIV ALIGN=right>%s <I><SMALL>This log was generated
               by PURR version %s.</SMALL></I></DIV>\n"""%(renderIcon(16),Purr.Version));
    fobj.write("</BODY></HTML>\n");
    fobj = None;
