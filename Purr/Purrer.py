# -*- coding: utf-8 -*-
# TODO:
# - add right-click options to New Entry menu: delete DP
# - store settings (such as pounce mode) inside the log
# - add a "Change dir" button. Integrate the catfight dialog into the
#   main window
# - in the browser: do not tell Purr to attach to a new directory
#   until the user presses the Purr button.
# - think of including verbatim code snippets in HTML

import configparser
import fcntl
import fnmatch
import glob
import os
import os.path
import re
import time
import traceback
from past.builtins import cmp

import Kittens.utils
from PyQt4.Qt import QObject, SIGNAL

import Purr
import Purr.Parsers
import Purr.Plugins
import Purr.Render
import Purr.RenderIndex
from Purr import Config, dprint, dprintf

# this string is used to create lock files
_lockstring = "%s:%d" % (os.uname()[1], os.getpid())


def parse_pattern_list(liststr):
    """Parses a list of filename patterns of the form "Description=ptt,patt,...;Description=patt,...
    Returns list of (description,[patterns]) tuples."""
    _re_patt = re.compile("^(.*)=(.*)")
    patterns = []
    for ss in liststr.split(';'):
        match = _re_patt.match(ss)
        if match:
            desc = match.group(1)
            patt = match.group(2).split(',')
            patterns.append((desc, patt))
    return patterns


def make_pattern_list(patterns):
    """Makes a string of filename patterns from a list of (description,[patterns]) tuples."""
    pattstrs = []
    for desc, patts in patterns:
        # ";," not allowed in descriptions or patterns
        patts = [p.replace(";", "").replace(",", "") for p in patts]
        desc = desc.replace(";", "").replace(",", "")
        pattstrs.append("%s=%s" % (desc, ','.join(patts)))
    return ";".join(pattstrs)


def _printexc(message, *args):
    print((message % args))
    traceback.print_exc()


def matches_patterns(filename, patterns):
    return bool([patt for patt in patterns if fnmatch.fnmatch(filename, patt)])


class Purrer(QObject):
    @staticmethod
    def is_purrlog(path):
        """Checks if path refers to a valid purrlog.
        Path must exist, and must contain either at least one directory called entry-YYYYMMDD-HHMMSS, or the file "dirconfig"
        """
        if not os.path.isdir(path):
            return False
        if list(filter(os.path.isdir, glob.glob(
                os.path.join(path, "entry-[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]-[0-9][0-9][0-9][0-9][0-9][0-9]")))):
            return True
        return os.path.exists(os.path.join(path, "dirconfig"))

    class WatchedFile(QObject):
        """A WatchedFile represents a single file being watched for changes."""

        def __init__(self, path, quiet=None, mtime=None, survive_deletion=False):
            """Creates watched file at 'path'. The 'quiet' flag is simply stored.
            If 'mtime' is not None, this will be the file's last-changed timestamp.
            If 'mtime' is None, it will use os.path.getmtime().
            The survive_deletion flag is used to mark watchers that should stay active even if the underlying file
            disappears. Watchers for old data products are created with this flag.
            """
            QObject.__init__(self)
            self.path = path
            self.enabled = True
            self.quiet = quiet
            dprintf(3, "creating WatchedFile %s, mtime %s (%f)\n", self.path,
                    time.strftime("%x %X", time.localtime(mtime or self.getmtime())), mtime or 0)
            self.mtime = mtime or self.getmtime()
            self.survive_deletion = survive_deletion
            self.disappeared = False

        def getmtime(self):
            """Returns the file's modification time.
            Returns None on access error (i.e. file doesn't exist)"""
            try:
                return os.path.getmtime(self.path)
            except:
                return None

        def isUpdated(self):
            """Checks if file was updated (i.e. mtime changed) since last check. Returns True if so.
            Returns None on access error."""
            if not self.enabled:
                return None
            mtime = self.getmtime()
            if mtime is None:
                return None
            # clear disappeared flag
            self.disappeared = False
            # compare m,times -- add .1 sec margin since float numbers may get clobbered during
            # conversion
            updated = (mtime or 0) > (self.mtime or 0) + .1
            if updated:
                dprintf(4, "WatchedFile %s is updated: mtime %f %s, old mtime %f %s\n", self.path,
                        mtime, time.strftime("%x %X", time.localtime(mtime)),
                        self.mtime, time.strftime("%x %X", time.localtime(self.mtime)))
            self.mtime = mtime
            return updated

        def newFiles(self):
            """Checks if there are any new files, returns iterable of (full) paths.
            (For a single file, this is just the file itself, if it has been updated.)
            Returns None on access error."""
            updated = self.isUpdated()
            if updated is None:
                return None
            return (updated and [self.path]) or []

    class WatchedDir(WatchedFile):
        """A WatchedDir represents a directory being watched for new files.
        """

        def __init__(self, path, watch_patterns=[], ignore_patterns=[], **kw):
            """Initializes directory.
            'ignore_patterns' is a list of patterns to be ignored.
            'watch_patterns' is a list of patterns to be watched.
            New files will be reported only if they don't match any of the ignore patterns, or
            match a watch pattern.
            All other arguments as per WatchedFile
            """
            Purrer.WatchedFile.__init__(self, path, **kw)
            self.watch_patterns = watch_patterns
            self.ignore_patterns = ignore_patterns
            self._newfiles = []
            # the self.fileset attribute gives the current directory content
            try:
                self.fileset = set(os.listdir(self.path))
            except:
                _printexc("Error doing listdir(%s)" % self.path)
                traceback.print_exc()
                self.fileset = None;  # this indicates a read error
                return
            # check for files created after the supplied timestamp
            if self.getmtime() > self.mtime:
                dprintf(2, "%s modified since last run (%f vs %f), checking for new files\n", self.path,
                        self.getmtime(), self.mtime)
                for fname in self.fileset:
                    # ignore files from ignore list
                    if matches_patterns(fname, ignore_patterns) and not matches_patterns(fname, watch_patterns):
                        dprintf(5, "%s: matches ignore list but not watch list, skipping\n", fname)
                        continue
                    fullname = os.path.join(self.path, fname)
                    # check creation time against our timestamp
                    try:
                        ctime = os.path.getctime(fullname)
                    except:
                        _printexc("Error getting ctime for %s, ignoring", fname)
                        continue
                    if ctime > self.mtime:
                        dprintf(4, "%s: new file (created %s)\n", fullname,
                                time.strftime("%x %X", time.localtime(ctime)))
                        # append basename to _newfiles: full path added in newFiles() below
                        self._newfiles.append(fname)

        def newFiles(self):
            """Returns new files (since last call to newFiles, or since creation).
            Return value is an iterable of (full) paths.
            Returns None on access error."""
            if not self.enabled:
                return None
            if self.fileset is None:
                return None
            newfiles = set(self._newfiles);  # some newfiles may have been found in __init__
            self._newfiles = []
            updated = self.isUpdated()
            if updated is None:
                return None
            elif updated:
                try:
                    fileset1 = set(os.listdir(self.path))
                except:
                    _printexc("Error doing listdir(%s)" % self.path)
                    traceback.print_exc()
                    self.fileset = None
                    return None
                newfiles.update(fileset1.difference(self.fileset))
                self.fileset = fileset1
            # skip new files in ignore list
            # also skip new files with older timestamps -- these may have been restored from the archive
            nfs = []
            for file in newfiles:
                if matches_patterns(file, self.ignore_patterns) and not matches_patterns(file, self.watch_patterns):
                    continue
                path = os.path.join(self.path, file)
                # try:
                #  mtime = os.path.getmtime(path)
                # except:
                #  _printexc("Error doing getmtime(%s), omitting"%path)
                #  continue
                # if mtime >= self.mtime:
                ## Don't want to do the above check really: new files may actually have an mtime < dir mtime.
                ## If file is new, that's reason enough to include it.
                nfs.append(path)
            return nfs

    class WatchedSubdir(WatchedDir):
        """A WatchedSubdir represents a directory being watched for updates
        to specific files (called "canaries") within that directory. The directory itself
        is reported as a "new file" if the directory mtime changes, or a canary has changed.
        """

        def __init__(self, path, canary_patterns=[], **kw):
            Purrer.WatchedDir.__init__(self, path, **kw)
            self.canary_patterns = canary_patterns
            self.canaries = {}
            # if no read errors, make up list of canaries from canary patterns
            if self.fileset is not None:
                for fname in self.fileset:
                    if matches_patterns(fname, canary_patterns):
                        fullname = os.path.join(self.path, fname)
                        self.canaries[fullname] = Purrer.WatchedFile(fullname, mtime=self.mtime)
                        dprintf(3, "watching canary file %s, timestamp %s\n",
                                fullname, time.strftime("%x %X", time.localtime(self.mtime)))

        def newFiles(self):
            """Returns new files (since last call to newFiles, or since creation).
            The only possible new file is the subdirectory itself, which is considered
            new if updated, or if a canary has changed.
            Return value is an iterable, or None on access error."""
            # check directory itself for updates
            if self.fileset is None:
                return None
            # check for new files first
            newfiles = Purrer.WatchedDir.newFiles(self)
            if newfiles is None:
                return None
            # this timestamp is assigned to all canaries when directory has changed
            timestamp = time.time()
            canaries_updated = False
            # check for new canaries among new files
            if newfiles:
                dprintf(3, "directory %s is updated\n", self.path)
                for fname in newfiles:
                    if matches_patterns(os.path.basename(fname), self.canary_patterns):
                        self.canaries[fname] = Purrer.WatchedFile(fname, mtime=timestamp)
                        dprintf(3, "watching new canary file %s, timestamp %s\n",
                                fname, time.strftime("%x %X", time.localtime(timestamp)))
            # else check current canaries for updates
            else:
                for filename, watcher in list(self.canaries.items()):
                    updated = watcher.isUpdated()
                    if updated is None:
                        dprintf(2, "access error on canary %s, will no longer be watched", filename)
                        del self.canaries[filename]
                        continue
                    elif updated:
                        dprintf(3, "canary %s is updated\n", filename)
                        newfiles = True;  # this is treated as a bool below
                        break
                # now, if directory has updated, reset timestamps on all canaries
                if newfiles:
                    for watcher in list(self.canaries.values()):
                        watcher.mtime = timestamp
            # returns ourselves (as new file) if something has updated
            return (newfiles and [self.path]) or []

    def __init__(self, purrlog, watchdirs=None):
        QObject.__init__(self)
        # load and parse configuration
        # watched files
        watch = Config.get("watch-patterns", "Images=*fits,*FITS,*jpg,*png;TDL configuration=.tdl.conf")
        self._watch = parse_pattern_list(watch)
        self._watch_patterns = set()
        for desc, patts in self._watch:
            self._watch_patterns.update(patts)
        dprint(1, "watching patterns", self._watch_patterns)
        # quietly watched files (dialog is not popped up)
        watch = Config.get("watch-patterns-quiet", "TDL configuration=.tdl.conf")
        self._quiet = parse_pattern_list(watch)
        self._quiet_patterns = set()
        for desc, patts in self._quiet:
            self._quiet_patterns.update(patts)
        dprint(1, "quietly watching patterns", self._quiet_patterns)
        # ignored files
        ignore = Config.get("ignore-patterns",
                            "Hidden files=.*;Purr logs=*purrlog;MeqTree logs=meqtree.log;Python files=*.py*;Backup files=*~,*.bck;Measurement sets=*.MS,*.ms;CASA tables=table.f*,table.dat,table.info,table.lock")
        self._ignore = parse_pattern_list(ignore)
        self._ignore_patterns = set()
        for desc, patts in self._ignore:
            self._ignore_patterns.update(patts)
        dprint(1, "ignoring patterns", self._ignore_patterns)
        # watched subdirectories
        subdirs = Config.get("watch-subdirs", "MEP tables=*mep/funklets,table.dat")
        _re_patt = re.compile("^(.*)=(.*)/(.*)$")
        self._subdir_patterns = []
        for ss in subdirs.split(';'):
            match = _re_patt.match(ss)
            if match:
                desc = match.group(1)
                dir_patt = match.group(2).split(',')
                canary_patt = match.group(3).split(',')
                self._subdir_patterns.append((desc, dir_patt, canary_patt))
        dprint(1, "watching subdirectories", self._subdir_patterns)
        # attach to directories
        self.attached = False;  # will be True when we successfully attach
        self.other_lock = None;  # will be not None if another PURR holds a lock on this directory
        self.lockfile_fd = None
        self.lockfile_fobj = None
        self._attach(purrlog, watchdirs)

    def __del__(self):
        self.detach()

    def detach(self):
        if self.lockfile_fobj:
            try:
                self.lockfile_fobj.close()
                self.lockfile_fd = None
            except:
                pass
        if self.lockfile_fd:
            try:
                os.close(self.lockfile_fd)
                self.lockfile_fd = None
            except:
                pass
        self.attached = False

    class LockedError(RuntimeError):
        pass

    class LockFailError(RuntimeError):
        pass

    def _attach(self, purrlog, watchdirs=None):
        """Attaches Purr to a purrlog directory, and loads content.
        Returns False if nothing new has been loaded (because directory is the same),
        or True otherwise."""
        purrlog = os.path.abspath(purrlog)
        dprint(1, "attaching to purrlog", purrlog)
        self.logdir = purrlog
        self.indexfile = os.path.join(self.logdir, "index.html")
        self.logtitle = "Unnamed log"
        self.timestamp = self.last_scan_timestamp = time.time()
        self._initIndexDir()
        # reset internal state
        self.ignorelistfile = None
        self.autopounce = False
        self.watched_dirs = []
        self.entries = []
        self._default_dp_props = {}
        self.watchers = {}
        self.temp_watchers = {}
        self.attached = False
        self._watching_state = {}
        # check that we hold a lock on the directory
        self.lockfile = os.path.join(self.logdir, ".purrlock")
        # try to open lock file for r/w
        try:
            self.lockfile_fd = os.open(self.lockfile, os.O_RDWR | os.O_CREAT)
        except:
            raise Purrer.LockFailError("failed to open lock file %s for writing" % self.lockfile)
        # try to acquire lock on the lock file
        try:
            fcntl.lockf(self.lockfile_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except:
            other_lock = os.fdopen(self.lockfile_fd, 'r').read()
            self.lockfile_fd = None
            raise Purrer.LockedError(other_lock)
        # got lock, write our ID to the lock file
        global _lockstring
        try:
            self.lockfile_fobj = os.fdopen(self.lockfile_fd, 'w')
            self.lockfile_fobj.write(_lockstring)
            self.lockfile_fobj.flush()
            os.fsync(self.lockfile_fd)
        except:
            raise
        #      raise Purrer.LockFailError("cannot write to lock file %s"%self.lockfile)
        # load log state if log directory already exists
        if os.path.exists(self.logdir):
            _busy = Purr.BusyIndicator()
            if os.path.exists(self.indexfile):
                try:
                    parser = Purr.Parsers.LogIndexParser()
                    for line in open(self.indexfile):
                        parser.feed(line)
                    self.logtitle = parser.title or self.logtitle
                    self.timestamp = parser.timestamp or self.timestamp
                    dprintf(2, "attached log '%s', timestamp %s\n",
                            self.logtitle, time.strftime("%x %X", time.localtime(self.timestamp)))
                except:
                    traceback.print_exc()
                    print(("Error parsing %s, reverting to defaults" % self.indexfile))
            # load log entries
            entries = []
            for fname in os.listdir(self.logdir):
                pathname = os.path.join(self.logdir, fname)
                if Purr.LogEntry.isValidPathname(pathname):
                    try:
                        entry = Purr.LogEntry(load=pathname)
                        dprint(2, "loaded log entry", pathname)
                    except:
                        print(("Error loading entry %s, skipping" % fname))
                        traceback.print_exc()
                        continue
                    entries.append(entry)
                else:
                    dprint(2, fname, "is not a valid Purr entry")
            # sort log entires by timestamp
            import six
            if six.PY2:
                entries.sort(lambda a, b: cmp(a.timestamp, b.timestamp))
            else:
                from past.builtins import cmp
                from functools import cmp_to_key
                entries.sort(key = cmp_to_key(lambda a, b: cmp(a.timestamp, b.timestamp)))
            self.setLogEntries(entries, save=False)
            # update own timestamp
            if entries:
                self.timestamp = max(self.timestamp, entries[-1].timestamp)
        # else logfile doesn't exist, create it
        else:
            self._initIndexDir()
        # load configuration if it exists
        # init config file
        self.dirconfig = configparser.RawConfigParser()
        self.dirconfigfile = os.path.join(self.logdir, "dirconfig")
        if os.path.exists(self.dirconfigfile):
            try:
                self.dirconfig.read(self.dirconfigfile)
            except:
                print(("Error loading config file %s" % self.dirconfigfile))
                traceback.print_exc()
            # load directory configuration
            for dirname in self.dirconfig.sections():
                try:
                    watching = self.dirconfig.getint(dirname, "watching")
                except:
                    watching = Purr.WATCHED
                dirname = os.path.expanduser(dirname)
                self.addWatchedDirectory(dirname, watching, save_config=False)
        # start watching the specified directories
        for name in (watchdirs or []):
            self.addWatchedDirectory(name, watching=None)
        # Finally, go through list of ignored files and mark their watchers accordingly.
        # The ignorelist is a list of lines of the form "timestamp filename", giving the timestamp when a
        # file was last "ignored" by the purrlog user.
        self.ignorelistfile = os.path.join(self.logdir, "ignorelist")
        if os.path.exists(self.ignorelistfile):
            # read lines from file, ignore exceptions
            ignores = {}
            try:
                for line in open(self.ignorelistfile).readlines():
                    timestamp, policy, filename = line.strip().split(" ", 2)
                    # update dictiornary with latest timestamp
                    ignores[filename] = int(timestamp), policy
            except:
                print(("Error reading %s" % self.ignorelistfile))
                traceback.print_exc()
            # now scan all listed files, and make sure their watchers' mtime is no older than the given
            # last-ignore-timestamp. This ensures that we don't pounce on these files after restarting purr.
            for filename, (timestamp, policy) in list(ignores.items()):
                watcher = self.watchers.get(filename, None)
                if watcher:
                    watcher.mtime = max(watcher.mtime, timestamp)
        # init complete
        self.attached = True
        return True

    def setWatchedFilePatterns(self, watch, ignore=[]):
        self._watch = watch
        self._ignore = ignore
        self._watch_patterns = set()
        for desc, patts in self._watch:
            self._watch_patterns.update(patts)
        dprint(1, "watching patterns", self._watch_patterns)
        self._ignore_patterns = set()
        for desc, patts in self._ignore:
            self._ignore_patterns.update(patts)
        dprint(1, "ignoring patterns", self._ignore_patterns)
        Config.set("watch-patterns", make_pattern_list(self._watch))
        Config.set("ignore-patterns", make_pattern_list(self._ignore))

    def setWatchingState(self, path, watching, save_config=True):
        dprintf(2, "%s: watching state is %d\n", path, watching)
        self._watching_state[path] = watching
        path = Kittens.utils.collapseuser(path)
        if watching == Purr.REMOVED:
            if self.dirconfig.has_section(path):
                self.dirconfig.remove_section(path)
        else:
            if not self.dirconfig.has_section(path):
                self.dirconfig.add_section(path)
            self.dirconfig.set(path, "watching", str(watching))
        if save_config:
            self.dirconfig.write(open(self.dirconfigfile, 'wt'))

    def watchingState(self, pathname):
        return self._watching_state[pathname]

    def watchedDirectories(self):
        return [(dd, state) for dd, state in list(self._watching_state.items()) if state != Purr.REMOVED]

    def addWatchedDirectory(self, dirname, watching=Purr.WATCHED, save_config=True):
        """Starts watching the specified directories for changes"""
        # see if we're alredy watching this exact set of directories -- do nothing if so
        dirname = Purr.canonizePath(dirname)
        # do nothing if already watching
        if dirname in self.watched_dirs:
            dprint(1, "addWatchDirectory(): already watching %s\n", dirname)
            # watching=None means do not change the watch-state
            if watching is None:
                return
        else:
            if watching is None:
                watching = Purr.WATCHED
            # make watcher object
            wdir = Purrer.WatchedDir(dirname, mtime=self.timestamp,
                                     watch_patterns=self._watch_patterns, ignore_patterns=self._ignore_patterns)
            # fileset=None indicates error reading directory, so ignore it
            if wdir.fileset is None:
                print(("There was an error reading the directory %s, will stop watching it." % dirname))
                self.setWatchingState(dirname, Purr.REMOVED, save_config=True)
                return
            self.watchers[dirname] = wdir
            self.watched_dirs.append(dirname)
            dprintf(2, "watching directory %s, mtime %s, %d files\n",
                    dirname, time.strftime("%x %X", time.localtime(wdir.mtime)), len(wdir.fileset))
            # find files in this directory matching the watch_patterns, and watch them for changes
            watchset = set()
            for patt in self._watch_patterns:
                watchset.update(fnmatch.filter(wdir.fileset, patt))
            for fname in watchset:
                quiet = matches_patterns(fname, self._quiet_patterns)
                fullname = Purr.canonizePath(os.path.join(dirname, fname))
                if fullname not in self.watchers:
                    wfile = Purrer.WatchedFile(fullname, quiet=quiet, mtime=self.timestamp)
                    self.watchers[fullname] = wfile
                    dprintf(3, "watching file %s, timestamp %s, quiet %d\n",
                            fullname, time.strftime("%x %X", time.localtime(wfile.mtime)), quiet)
            # find subdirectories  matching the subdir_patterns, and watch them for changes
            for fname in wdir.fileset:
                fullname = Purr.canonizePath(os.path.join(dirname, fname))
                if os.path.isdir(fullname):
                    for desc, dir_patts, canary_patts in self._subdir_patterns:
                        if matches_patterns(fname, dir_patts):
                            quiet = matches_patterns(fname, self._quiet_patterns)
                            wdir = Purrer.WatchedSubdir(fullname, canary_patterns=canary_patts, quiet=quiet,
                                                        mtime=self.timestamp)
                            self.watchers[fullname] = wdir
                            dprintf(3, "watching subdirectory %s/{%s}, timestamp %s, quiet %d\n",
                                    fullname, ",".join(canary_patts),
                                    time.strftime("%x %X", time.localtime(wdir.mtime)), quiet)
                            break
        # set state and save config
        self.setWatchingState(dirname, watching, save_config=save_config)

    def setLogTitle(self, title, save=True):
        self.logtitle = title
        if save:
            self.save()

    def addLogEntry(self, entry, save=True):
        """This is called when a new log entry is created"""
        # create log directory if it doesn't exist
        # error will be thrown if this is not possible
        _busy = Purr.BusyIndicator()
        self._initIndexDir()
        # discard temporary watchers -- these are only used to keep track of
        # deleted files
        self.temp_watchers = {}
        # ignored entries are only there to carry info on ignored data products
        # All we do is save them, and update DP policies based on them
        if entry.ignore:
            entry.save(self.logdir)
        # proper entries are added to list
        else:
            self.entries.append(entry)
            Purr.progressMessage("Saving new log entry")
            # find previous entry -- skip over "ignore" entries
            for prev in self.entries[-2::-1]:
                if not prev.ignore:
                    break
            else:
                prev = None
            entry.setLogDirectory(self.logdir)
            entry.setPrevUpNextLinks(prev=prev, up=os.path.join("..", Purr.RenderIndex.INDEX))
            entry.save()
            self.timestamp = self.last_scan_timestamp
            # regenerate links of previous entry
            prev and prev.generateIndex()
            # and our log may need to be regenerated
            if save:
                self.save()
        self.updatePoliciesFromEntry(entry, new=True)

    def getLogEntries(self):
        return self.entries

    def setLogEntries(self, entries, save=True, update_policies=True):
        """Sets list of log entries. If save=True, saves the log. If update_policies=True, also updates default policies based
        on these entries"""
        prev = None;  # "previous" valid entry for "Prev" link
        uplink = os.path.join("..", Purr.RenderIndex.INDEX);  # "Up" link
        self.entries = []
        for entry in entries:
            if not entry.ignore:
                entry.setPrevUpNextLinks(prev=prev, up=uplink)
                prev = entry
                self.entries.append(entry)
        if save:
            self.save()
        if update_policies:
            # populate default policies and renames based on entry list
            self._default_dp_props = {}
            for entry in entries:
                self.updatePoliciesFromEntry(entry)
            dprint(4, "default policies:", self._default_dp_props)

    def deleteLogEntries(self, del_entries, save=True):
        """Deletes given list of entries from the log. Some entries' index.html files may be updated to reflect changes in prev/next links. If save=True, re-saves the log itself."""
        prev_valid = prev_deleted = None
        # fix Next/Prev links in remaining entries
        newents = []
        updated = set()
        for ent in self.entries:
            if not ent.ignore:
                if ent in del_entries:
                    prev_deleted = ent
                else:
                    if prev_deleted:
                        ent.setPrevUpNextLinks(prev=prev_valid)
                        prev_valid and prev_valid.generateIndex()
                        ent.generateIndex()
                        prev_deleted = None
                    prev_valid = ent
                    newents.append(ent)
            else:
                newents.append(ent)
        # fix last "Next" link if we had a deleted entry followed by nothing
        if prev_deleted and prev_valid:
            prev_valid.setPrevUpNextLinks(next='')
            prev_valid.generateIndex()
        # regenerate indices
        for ent in newents:
            if id(ent) in updated:
                ent.generateIndex()
        self.entries = newents
        if save:
            self.save()

    def updatePoliciesFromEntry(self, entry, new=True):
        # populate default policies and renames based on entry list
        for dp in entry.dps:
            # add default policy
            basename = os.path.basename(dp.sourcepath)
            self._default_dp_props[basename] = dp.policy, dp.filename, dp.comment
            dprintf(4, "file %s: default policy is %s\n", basename, dp.policy)
            # make new watchers for non-ignored files
            if dp.ignored:
                # if ignorelistfile is not set, then we're being called from within
                # _attach(), when older log entries are being loaded. No need to write the file then.
                if new and self.ignorelistfile and os.path.exists(dp.sourcepath):
                    try:
                        open(self.ignorelistfile, 'a').write(
                            "%d %s %s\n" % (os.path.getmtime(dp.sourcepath), dp.policy, dp.sourcepath))
                    except:
                        print(("Error writing %s" % self.ignorelistfile))
                        traceback.print_exc()
            else:
                watcher = self.watchers.get(dp.sourcepath, None)
                # if watcher already exists, update timestamp
                if watcher:
                    if watcher.mtime < dp.timestamp:
                        watcher.mtime = dp.timestamp
                        dprintf(4, "file %s, updating timestamp to %s\n",
                                dp.sourcepath, time.strftime("%x %X", time.localtime(dp.timestamp)))
                # else create new watcher
                else:
                    wfile = Purrer.WatchedFile(dp.sourcepath, quiet=dp.quiet, mtime=dp.timestamp, survive_deletion=True)
                    self.watchers[dp.sourcepath] = wfile
                    dprintf(4, "watching file %s, timestamp %s\n",
                            dp.sourcepath, time.strftime("%x %X", time.localtime(dp.timestamp)))

    def _relIndexLink(self):
        """Returns relative link to index.html of this entry. Link will be of the form ../entry-xxx/index.html"""
        return os.path.join("..", os.path.basename(self.pathname), "index.html")

    def _initIndexDir(self):
        """makes sure purrlog directory is properly set up"""
        if not os.path.exists(self.logdir):
            os.mkdir(self.logdir)
            dprint(1, "created", self.logdir)
        Purr.RenderIndex.initIndexDir(self.logdir)

    def save(self, refresh=False):
        """Saves the log.
        If refresh is set to a timestamp, will regenerate everything from scratch.
        """
        # create directory if it doesn't exist
        # error will be thrown if this is not possible
        _busy = Purr.BusyIndicator()
        Purr.progressMessage("Generating index in %s" % self.logdir)
        self._initIndexDir()
        # if refresh is True, re-save all entries.
        if refresh:
            refresh = time.time()
            for i, entry in enumerate(self.entries):
                entry.save(refresh=refresh)
        Purr.RenderIndex.writeLogIndex(self.logdir, self.logtitle, self.timestamp, self.entries, refresh=refresh)
        Purr.progressMessage("Wrote %s" % self.logdir)

    def rescan(self):
        """Checks files and directories on watchlist for updates, rescans them for new data products.
        If any are found, returns them. Skips those in directories whose watchingState is set to Purr.UNWATCHED.
        """
        if not self.attached:
            return
        dprint(5, "starting rescan")
        newstuff = {};  # this accumulates names of new or changed files. Keys are paths, values are 'quiet' flag.
        # store timestamp of scan
        self.last_scan_timestamp = time.time()
        # go through watched files/directories, check for mtime changes
        for path, watcher in list(self.watchers.items()):
            # get list of new files from watcher
            newfiles = watcher.newFiles()
            # None indicates access error, so drop it from watcher set
            if newfiles is None:
                if watcher.survive_deletion:
                    dprintf(5, "access error on %s, but will still be watched\n", watcher.path)
                else:
                    dprintf(2, "access error on %s, will no longer be watched\n", watcher.path)
                    del self.watchers[path]
                if not watcher.disappeared:
                    self.emit(SIGNAL("disappearedFile"), path)
                    watcher.disappeared = True
                continue
            dprintf(5, "%s: %d new file(s)\n", watcher.path, len(newfiles))
            # if a file has its own watcher, and is independently reported by a directory watcher, skip the directory's
            # version and let the file's watcher report it. Reason for this is that the file watcher may have a more
            # up-to-date timestamp, so we trust it over the dir watcher.
            newfiles = [p for p in newfiles if p is path or p not in self.watchers]
            # skip files in self._unwatched_paths
            newfiles = [filename for filename in newfiles if
                        self._watching_state.get(os.path.dirname(filename)) > Purr.UNWATCHED]
            # Now go through files and add them to the newstuff dict
            for newfile in newfiles:
                # if quiet flag is explicitly set on watcher, enforce it
                # if not pouncing on directory, also add quietly
                if watcher.quiet or self._watching_state.get(os.path.dirname(newfile)) < Purr.POUNCE:
                    quiet = True
                # else add quietly if file is not in the quiet patterns
                else:
                    quiet = matches_patterns(os.path.basename(newfile), self._quiet_patterns)
                # add file to list of new products. Since a file may be reported by multiple
                # watchers, make the quiet flag a logical AND of all the quiet flags (i.e. DP will be
                # marked as quiet only if all watchers report it as quiet).
                newstuff[newfile] = quiet and newstuff.get(newfile, True)
                dprintf(4, "%s: new data product, quiet=%d (watcher quiet: %s)\n", newfile, quiet, watcher.quiet)
                # add a watcher for this file to the temp_watchers list. this is used below
                # to detect renamed and deleted files
                self.temp_watchers[newfile] = Purrer.WatchedFile(newfile)
        # now, go through temp_watchers to see if any newly pounced-on files have disappeared
        for path, watcher in list(self.temp_watchers.items()):
            # get list of new files from watcher
            if watcher.newFiles() is None:
                dprintf(2, "access error on %s, marking as disappeared", watcher.path)
                del self.temp_watchers[path]
                self.emit(SIGNAL("disappearedFile"), path)
        # if we have new data products, send them to the main window
        return self.makeDataProducts(iter(list(newstuff.items())))

    def makeDataProducts(self, files, unbanish=False, unignore=False):
        """makes a list of DPs from a list of (filename,quiet) pairs.
        If unbanish is False, DPs with a default "banish" policy will be skipped.
        Symlinks will be resolved, and non-unique filenames removed from list.
        """
        paths = set()
        dps = []
        for filename, quiet in files:
            filename = filename.rstrip('/')
            sourcepath = Purr.canonizePath(filename)
            if sourcepath not in paths:
                paths.add(sourcepath)
                filename = os.path.basename(filename)
                policy, filename, comment = self._default_dp_props.get(filename, ("copy", filename, ""))
                dprintf(4, "%s: default policy is %s,%s,%s\n", sourcepath, policy, filename, comment)
                if policy == "banish":
                    if unbanish:
                        policy = "copy"
                    else:
                        continue
                if unignore and policy == "ignore":
                    policy = "copy"
                dps.append(Purr.DataProduct(filename=filename, sourcepath=sourcepath,
                                            policy=policy, comment=comment, quiet=quiet))
        import six
        from past.builtins import cmp
        from functools import cmp_to_key
        if six.PY3:
            return sorted(dps, key=cmp_to_key(lambda a, b: cmp(a.filename, b.filename)))
        else:
            return sorted(dps, lambda a, b: cmp(a.filename, b.filename))
