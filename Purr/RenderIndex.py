# -*- coding: utf-8 -*-
import os
import os.path
import traceback

try:
    from PyQt4.Qt import *
except ImportError as e:
    print("Failed to load Qt4. Purr is not available")
    raise e

import Purr
import Purr.Render
from Purr.Render import quote_url

FULLINDEX = "fullindex.html"
INDEX = "index.html"

PURR_ICONS = {16: "purr16.png", 24: "purr24.png", 32: "purr32.png"}


def initIndexDir(logdir):
    for sz, filename in list(PURR_ICONS.items()):
        path = os.path.join(logdir, filename)
        if not os.path.exists(path):
            Purr.pixmaps.purr_logo.pm().scaled(QSize(sz, sz), Qt.KeepAspectRatioByExpanding,
                                               Qt.SmoothTransformation).save(path)


def renderIcon(size, path=None):
    filename = PURR_ICONS[size]
    if path:
        filename = os.path.join(path, filename)
    return """<IMG SRC="%s"></IMG>""" % quote_url(filename)


def writeLogIndex(logdir, title, timestamp, entries, refresh=0):
    logdir = os.path.normpath(os.path.abspath(logdir))
    fullindex = os.path.join(logdir, FULLINDEX)
    tocindex = os.path.join(logdir, INDEX)

    # if 5 entries or less, do an index only, and remove the fullindex
    if len(entries) <= 5:
        if os.path.exists(fullindex):
            try:
                os.remove(fullindex)
            except:
                print(("Error removing %s:" % fullindex))
                traceback.print_exc()
        fullindex = tocindex
        tocindex = None

    # generate TOC index, if asked to
    if tocindex:
        fobj = open(tocindex, "wt")
        # write index.html
        fobj.write("""<HTML><BODY>\n
      <TITLE>%s</TITLE>

      <H1><A CLASS="TITLE" TIMESTAMP=%.6f>%s</A></H1>

      """ % (title, timestamp, title))
        fobj.write(
            """<DIV ALIGN=right><P><A HREF=%s>Printable version (single HTML page).</A></P></DIV>\n\n""" % FULLINDEX)
        # write entries
        for i, entry in enumerate(entries):
            path = os.path.normpath(os.path.abspath(entry.index_file))
            if path.startswith(logdir + '/'):
                path = path[(len(logdir) + 1):]
            fobj.write("""<P><A HREF="%s">%d. %s</A></P>\n\n""" % (quote_url(path), i + 1, entry.title))
        # write footer
        fobj.write("<HR>\n\n")
        fobj.write("""<DIV ALIGN=right>%s <I><SMALL>This log was generated
               by PURR version %s.</SMALL></I></DIV>\n""" % (renderIcon(16), Purr.Version))
        fobj.write("</BODY></HTML>\n")
        fobj = None

    # generate full index, if asked to
    if fullindex:
        fobj = open(fullindex, "wt")
        # write index.html
        fobj.write("""<HTML><BODY>\n
      <TITLE>%s</TITLE>

      <H1><A CLASS="TITLE" TIMESTAMP=%.6f>%s</A></H1>

      """ % (title, timestamp, title))
        # write entries
        for entry in entries:
            fobj.write(entry.renderIndex(os.path.join(os.path.basename(entry.pathname), ""), refresh=refresh))
        # write footer
        fobj.write("<HR>\n")
        fobj.write("""<DIV ALIGN=right>%s <I><SMALL>This log was generated
               by PURR version %s.</SMALL></I></DIV>\n""" % (renderIcon(16), Purr.Version))
        fobj.write("</BODY></HTML>\n")
        fobj = None
