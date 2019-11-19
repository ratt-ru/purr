#!/usr/bin/python
# -*- coding: utf-8 -*-

# loading file into karma:
#   ksend -add_connection unix 9975 multi_array kvis -load ARRAY:FILE0 img4096.fits
# ls /tmp/.KARMA-connections for port number
from PyQt4.Qt import QApplication
import sys


def trace_lines(frame, event, arg):
    if event == "line":
        print(("%s:%d" % (frame.f_code.co_filename, frame.f_lineno)))
    return trace_lines


# runs Purr standalone
if __name__ == "__main__":
    print("Welcome to PURR!")

    # parse options is the first thing we should do
    from optparse import OptionParser

    usage = "usage: %prog [options] <directories to watch>"
    parser = OptionParser(usage=usage)
    parser.add_option("-d", "--debug", dest="verbose", type="string", action="append", metavar="Context=Level",
                      help="(for debugging Python code) sets verbosity level of the named Python context. May be used multiple times.")
    parser.add_option("--trace", dest="trace", action="store_true",
                      help="(for debugging Python code) enables line tracing of Python statements")
    (options, rem_args) = parser.parse_args()

    if options.trace:
        sys.settrace(trace_lines)

    print("Please wait a second while the GUI starts up.")

    import sys
    import signal
    import os
    import os.path

    from PyQt4.Qt import *

    import Purr
    import Purr.MainWindow
    import Purr.Render
    import Purr.Startup

    app = QApplication(sys.argv)
    app.setDesktopSettingsAware(True)

    #  splash = QSplashScreen(Purr.pixmaps.purr_logo.pm())
    #  splash.showMessage("PURR!")
    #  splash.show()

    purrwin = Purr.MainWindow.MainWindow(None)

    try:
        if not Purr.Startup.startWizard(rem_args, purrwin):
            print("Cancelled by user")
            os._exit(1)
    except Purr.Startup.Error as err:
        print((err.error_message))
        os._exit(1)


    # handle SIGINT
    def sigint_handler(sig, stackframe):
        print("Caught Ctrl+C, PURR exiting...")
        purrwin.detachPurrlog()
        app.quit()


    signal.signal(signal.SIGINT, sigint_handler)

    app.exec_()

    os._exit(0)
