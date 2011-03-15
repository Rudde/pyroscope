""" PyroCore - Metafile Support.

    Copyright (c) 2009, 2010, 2011 The PyroScope Project <pyroscope.project@gmail.com>

    This program is free software; you can redistribute it and/or modify
    it under the terms of the GNU General Public License as published by
    the Free Software Foundation; either version 2 of the License, or
    (at your option) any later version.

    This program is distributed in the hope that it will be useful,
    but WITHOUT ANY WARRANTY; without even the implied warranty of
    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
    GNU General Public License for more details.

    You should have received a copy of the GNU General Public License along
    with this program; if not, write to the Free Software Foundation, Inc.,
    51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.
"""
from __future__ import with_statement

import re
import sys
import time
import stat
import math
import errno
import pprint
import fnmatch
import hashlib
import urlparse
from contextlib import closing

from pyrocore import config, error
from pyrocore.util import os, bencode, fmt, pymagic, types


# Allowed characters in a metafile filename or path
ALLOWED_NAME = re.compile(r"^[^/\\.~][^/\\]*$")

# Character sequences considered secret (roughly, any path part or query parameter
# that looks like an alphanumeric sequence or url-safe base64 string)
PASSKEY_RE = re.compile(r"(?<=[/=])[-_0-9a-zA-Z]{5,64}={0,3}(?=[/&]|$)")

# Non-secret exemptions
PASSKEY_OK = ("announce", "TrackerServlet",)

# List of all standard keys in a metafile
METAFILE_STD_KEYS = [i.split('.') for i in (
    "announce",
    "comment",
    "created by",
    "creation date",
    "encoding",
    "info",
    "info.length",
    "info.name",
    "info.piece length",
    "info.pieces",
    "info.private",
    "info.files",
    "info.files.length",
    "info.files.path",
)]


def console_progress():
    """ Return a progress indicator for consoles if
        stdout is a tty.
    """
    def progress(totalhashed, totalsize):
        msg = " " * 30
        if totalhashed < totalsize:
            msg = "%5.1f%% complete" % (totalhashed * 100.0 / totalsize)
        sys.stdout.write(msg + " \r")
        sys.stdout.flush()

    try:
        return progress if sys.stdout.isatty() else None
    except AttributeError:
        return None
        

def mask_keys(announce_url):
    """ Mask any passkeys (hex sequences) in an announce URL.
    """
    return PASSKEY_RE.sub(
        lambda m: m.group() if m.group() in PASSKEY_OK else "*" * len(m.group()),
        announce_url)


class MaskingPrettyPrinter(pprint.PrettyPrinter):
    """ A PrettyPrinter that masks strings in the object tree.
    """

    def format(self, obj, context, maxlevels, level):
        """ Mask obj if it looks like an URL, then pass it to the super class.
        """
        if isinstance(obj, basestring) and "://" in obj:
            obj = mask_keys(obj)
        return pprint.PrettyPrinter.format(self, obj, context, maxlevels, level)


def check_info(info):
    """ Validate info dict.
    
        Raise ValueError if validation fails.
    """
    if not isinstance(info, dict):
        raise ValueError("bad metainfo - not a dictionary")

    pieces = info.get("pieces")
    if not isinstance(pieces, basestring) or len(pieces) % 20 != 0:
        raise ValueError("bad metainfo - bad pieces key")

    piece_size = info.get("piece length")
    if not isinstance(piece_size, (int, long)) or piece_size <= 0:
        raise ValueError("bad metainfo - illegal piece length")

    name = info.get("name")
    if not isinstance(name, basestring):
        raise ValueError("bad metainfo - bad name (type is %r)" % type(name).__name__)
    if not ALLOWED_NAME.match(name):
        raise ValueError("name %s disallowed for security reasons" % name)

    if info.has_key("files") == info.has_key("length"):
        raise ValueError("single/multiple file mix")

    if info.has_key("length"):
        length = info.get("length")
        if not isinstance(length, (int, long)) or length < 0:
            raise ValueError("bad metainfo - bad length")
    else:
        files = info.get("files")
        if not isinstance(files, (list, tuple)):
            raise ValueError("bad metainfo - bad file list")

        for item in files:
            if not isinstance(item, dict):
                raise ValueError("bad metainfo - bad file value")

            length = item.get("length")
            if not isinstance(length, (int, long)) or length < 0:
                raise ValueError("bad metainfo - bad length")

            path = item.get("path")
            if not isinstance(path, (list, tuple)) or not path:
                raise ValueError("bad metainfo - bad path")

            for part in path:
                if not isinstance(part, basestring):
                    raise ValueError("bad metainfo - bad path dir")
                if not ALLOWED_NAME.match(part):
                    raise ValueError("path %s disallowed for security reasons" % part)

        file_paths = [os.sep.join(item["path"]) for item in files]
        if len(set(file_paths)) != len(file_paths):
            raise ValueError("bad metainfo - duplicate path")

    return info


def check_meta(meta):
    """ Validate meta dict.
    
        Raise ValueError if validation fails.
    """
    if not isinstance(meta, dict):
        raise ValueError("bad metadata - not a dictionary")
    if not isinstance(meta.get("announce"), basestring):
        raise ValueError("bad announce URL - not a string")
    check_info(meta.get("info"))

    return meta


def clean_meta(meta, including_info=False, log=None):
    """ Clean meta dict.
    """
    for key in meta.keys():
        if [key] not in METAFILE_STD_KEYS:
            if log:
                log.info("Removing key %r..." % (key,))
            del meta[key]

    if including_info:
        for key in meta["info"].keys():
            if ["info", key] not in METAFILE_STD_KEYS:
                if log:
                    log.info("Removing key %r..." % ("info." + key,))
                del meta["info"][key]

        for idx, entry in enumerate(meta["info"].get("files", [])):
            for key in entry.keys():
                if ["info", "files", key] not in METAFILE_STD_KEYS:
                    if log: 
                        log.info("Removing key %r from file #%d..." % (key, idx+1))
                    del entry[key]

    return meta


def assign_fields(meta, assignments):
    """ Takes a list of C{key=value} strings and
        assigns them to the given metafile.
        
        If just a key name is given (no '='), the field is removed.
    """
    for assignment in assignments:
        try:
            if '=' in assignment:
                field, val = assignment.split('=', 1)
            else:
                field, val = assignment, None
            
            if val and val[0] in "+-" and val[1:].isdigit():
                val = int(val, 10)

            # TODO: create dicts as we go, for now we can only assign into existing namespaces
            # TODO: Allow numerical indices, and "+" for append
            namespace = meta
            for key in field.split('.')[:-1]:
                namespace = namespace[key]
        except (KeyError, IndexError, TypeError, ValueError), exc:
            raise error.UserError("Bad assignment %r (%s)!" % (assignment, exc))
        else:
            if val is None:
                del namespace[field.split('.')[-1]]
            else:
                namespace[field.split('.')[-1]] = val

    return meta


def add_fast_resume(meta, datapath):
    """ Add fast resume data to a metafile dict.
    """
    # Get list of files
    files = meta["info"].get("files", None)
    single = files is None
    if single:
        if os.path.isdir(datapath):
            datapath = os.path.join(datapath, meta["info"]["name"])
        files = [types.Bunch(
            path=[os.path.abspath(datapath)],
            length=meta["info"]["length"],
        )]

    # Prepare resume data
    resume = meta.setdefault("libtorrent_resume", {})
    resume["bitfield"] = len(meta["info"]["pieces"]) // 20
    resume["files"] = []
    piece_length = meta["info"]["piece length"]
    offset = 0

    for fileinfo in files:
        # Get the path into the filesystem
        filepath = os.sep.join(fileinfo["path"])
        if not single:
            filepath = os.path.join(datapath, filepath)

        # Check file size
        if os.path.getsize(filepath) != fileinfo["length"]:
            raise OSError(errno.EINVAL, "File size mismatch for %r [is %d, expected %d]" % (
                filepath, os.path.getsize(filepath), fileinfo["length"],
            ))

        # Add resume data for this file
        resume["files"].append(dict(
            priority=1,
            mtime=int(os.path.getmtime(filepath)),
            completed=(offset+fileinfo["length"]+piece_length-1) // piece_length
                     - offset // piece_length,
        ))
        offset += fileinfo["length"]

    return meta


def info_hash(metadata):
    """ Return info hash as a string.
    """
    return hashlib.sha1(bencode.bencode(metadata['info'])).hexdigest().upper()


def data_size(metadata):
    """ Calculate the size of a torrent based on parsed metadata.
    """
    info = metadata['info']

    if info.has_key('length'):
        # Single file
        total_size = info['length']
    else:
        # Directory structure
        total_size = sum([f['length'] for f in info['files']])
    
    return total_size


class Metafile(object):
    """ A torrent metafile.
    """

    # Patterns of names to ignore
    IGNORE_GLOB = [
        "core", "CVS", ".*", "*~", "*.swp", "*.tmp", "*.bak",
        "[Tt]humbs.db", "[Dd]esktop.ini", "ehthumbs_vista.db",
    ]


    def __init__(self, filename, datapath=None):
        """ Initialize metafile.
        """
        self.filename = filename
        self.progress = None
        self.datapath = datapath
        self.ignore = self.IGNORE_GLOB[:]
        self.LOG = pymagic.get_class_logger(self)


    def _get_datapath(self):
        """ Get a valid datapath, else raise an exception.
        """
        if self._datapath is None:
            raise OSError(errno.ENOENT, "You didn't provide any datapath for %r" % self.filename)

        return self._datapath

    def _set_datapath(self, datapath):
        """ Set a datapath.
        """
        if datapath:
            self._datapath = datapath.rstrip(os.sep)
            self._fifo = int(stat.S_ISFIFO(os.stat(self.datapath).st_mode))
        else:
            self._datapath = None
            self._fifo = False

    datapath = property(_get_datapath, _set_datapath)


    def walk(self):
        """ Generate paths in "self.datapath".
        """
        # FIFO?
        if self._fifo:
            if self._fifo > 1:
                raise RuntimeError("INTERNAL ERROR: FIFO read twice!")
            self._fifo += 1
                
            # Read paths relative to directory containing the FIFO
            with closing(open(self.datapath, "r")) as fifo:
                while True:
                    relpath = fifo.readline().rstrip('\n')
                    if not relpath: # EOF?
                        break
                    self.LOG.debug("Read relative path %r from FIFO..." % (relpath,))
                    yield os.path.join(os.path.dirname(self.datapath), relpath)

            self.LOG.debug("FIFO %r closed!" % (self.datapath,))
                
        # Directory?
        elif os.path.isdir(self.datapath):
            # Walk the directory tree
            for dirpath, dirnames, filenames in os.walk(self.datapath): #, followlinks=True):
                # Don't scan blacklisted directories
                for bad in dirnames[:]:
                    if any(fnmatch.fnmatch(bad, pattern) for pattern in self.ignore):
                        dirnames.remove(bad)

                # Yield all filenames that aren't blacklisted
                for filename in filenames:
                    if not any(fnmatch.fnmatch(filename, pattern) for pattern in self.ignore):
                        #yield os.path.join(dirpath[len(self.datapath)+1:], filename)
                        yield os.path.join(dirpath, filename)

        # Single file
        else:
            # Yield the filename
            yield self.datapath


    def _calc_size(self):
        """ Get total size of "self.datapath".
        """
        return sum(os.path.getsize(filename)
            for filename in self.walk()
        )


    def _make_info(self, piece_size, progress, walker, piece_callback=None):
        """ Create info dict.
        """
        # These collect the file descriptions and piece hashes
        file_list = []
        pieces = []

        # Initialize progress state
        totalsize = -1 if self._fifo else self._calc_size()
        totalhashed = 0

        # Start a new piece
        sha1 = hashlib.sha1()
        done = 0
 
        # Hash all files
        for filename in walker:
            # Assemble file info
            filesize = os.path.getsize(filename)
            filepath = filename[len(os.path.dirname(self.datapath) if self._fifo else self.datapath):].lstrip(os.sep)
            file_list.append({
                "length": filesize, 
                "path": filepath.replace(os.sep, '/').split('/'),
            })
            self.LOG.debug("Hashing %r, size %d..." % (filename, filesize))
            
            # Open file and hash it
            fileoffset = 0
            handle = open(filename, "rb")
            try:
                while fileoffset < filesize:
                    # Read rest of piece or file, whatever is smaller
                    chunk = handle.read(min(filesize - fileoffset, piece_size - done))
                    sha1.update(chunk)
                    done += len(chunk)
                    fileoffset += len(chunk)
                    totalhashed += len(chunk)
                    
                    # Piece is done
                    if done == piece_size:
                        pieces.append(sha1.digest())
                        if piece_callback:
                            piece_callback(filename, pieces[-1])
                        
                        # Start a new piece
                        sha1 = hashlib.sha1()
                        done = 0

                    # Report progress
                    if progress:
                        progress(totalhashed, totalsize)
            finally:
                handle.close()

        # Add hash of partial last piece
        if done > 0:
            pieces.append(sha1.digest())
            if piece_callback:
                piece_callback(filename, pieces[-1])

        # Build the meta dict
        metainfo = {
            "pieces": "".join(pieces),
            "piece length": piece_size, 
            "name": os.path.basename(self.datapath),
        }

        # Handle directory/FIFO vs. single file        
        if self._fifo or os.path.isdir(self.datapath):
            metainfo["files"] = file_list
        else:
            metainfo["length"] = totalhashed

        # Return validated info dict
        return check_info(metainfo)


    def _make_meta(self, tracker_url, root_name, private, progress):
        """ Create torrent dict.
        """
        # Calculate piece size
        if self._fifo:
            # TODO we need to add a (command line) param, probably for total data size
            # for now, always 1MB
            piece_size_exp = 20 
        else:
            total_size = self._calc_size()
            if total_size:
                piece_size_exp = int(math.log(total_size) / math.log(2)) - 9
            else:
                piece_size_exp = 0

        piece_size_exp = min(max(15, piece_size_exp), 24)
        piece_size = 2 ** piece_size_exp

        # Build info hash
        info = self._make_info(piece_size, progress, self.walk() if self._fifo else sorted(self.walk()))

        # Enforce unique hash per tracker
        info["x_cross_seed"] = hashlib.md5(tracker_url).hexdigest()

        # Set private flag
        if private:
            info["private"] = 1

        # Freely chosen root name (default is basename of the data path)
        if root_name:
            info["name"] = root_name

        # Torrent metadata
        meta = {
            "info": info, 
            "announce": tracker_url.strip(), 
        }

        #XXX meta["encoding"] = "UTF-8"

        # Return validated meta dict
        return check_meta(meta)


    def create(self, datapath, tracker_urls, comment=None, root_name=None, 
                     created_by=None, private=False, no_date=False, progress=None,
                     callback=None):
        """ Create a metafile with the path given on object creation. 
            Returns the last metafile dict that was written (as an object, not bencoded).
        """
        if datapath:
            self.datapath = datapath

        try:
            tracker_urls = ['' + tracker_urls]
        except TypeError:
            tracker_urls = list(tracker_urls)
        multi_mode = len(tracker_urls) > 1

        # TODO add optimization so the hashing happens only once for multiple URLs!
        for tracker_url in tracker_urls:
            # Lookup announce URLs from config file
            try:
                if urlparse.urlparse(tracker_url).scheme:
                    tracker_alias = urlparse.urlparse(tracker_url).netloc.split(':')[0].split('.')
                    tracker_alias = tracker_alias[-2 if len(tracker_alias) > 1 else 0]
                else:
                    tracker_alias, tracker_url = config.lookup_announce_alias(tracker_url)
                    tracker_url = tracker_url[0]
            except (KeyError, IndexError):
                raise error.UserError("Bad tracker URL %r, or unknown alias!" % (tracker_url,))
        
            # Determine metafile name
            output_name = self.filename
            if multi_mode:
                # Add 2nd level of announce URL domain to metafile name
                output_name = list(os.path.splitext(output_name))
                try:
                    output_name[1:1] = '-' + tracker_alias
                except (IndexError,):
                    self.LOG.error("Malformed announce URL %r, skipping!" % (tracker_url,))
                    continue
                output_name = ''.join(output_name)

            # Hash the data
            self.LOG.info("Creating %r for %s %r..." % (
                output_name, "filenames read from" if self._fifo else "data in", self.datapath,
            ))
            meta = self._make_meta(tracker_url, root_name, private, progress)

            # Add optional fields
            if comment:
                meta["comment"] = comment
            if created_by:
                meta["created by"] = created_by
            if not no_date:
                meta["creation date"] = long(time.time())
            if callback:
                callback(meta)

            # Write metafile to disk
            self.LOG.debug("Writing %r..." % (output_name,))
            bencode.bwrite(output_name, meta)

        return meta


    def check(self, metainfo, datapath, progress=None):
        """ Check piece hashes of a metafile against the given datapath.
        """
        if datapath:
            self.datapath = datapath

        def check_piece(filename, piece):
            "Callback for new piece"
            if piece != metainfo["info"]["pieces"][check_piece.piece_index:check_piece.piece_index+20]:
                self.LOG.warn("Piece #%d: Hashes differ in file %r" % (check_piece.piece_index//20, filename))
            check_piece.piece_index += 20
        check_piece.piece_index = 0
            
        datameta = self._make_info(int(metainfo["info"]["piece length"]), progress, 
            [datapath] if "length" in metainfo["info"] else
            (os.path.join(*([datapath] + i["path"])) for i in metainfo["info"]["files"]),
            piece_callback=check_piece
        )
        return datameta["pieces"] == metainfo["info"]["pieces"]


    def listing(self, masked=True):
        """ List torrent info & contents. Returns a list of formatted lines.
        """
        # Assemble data
        metainfo = bencode.bread(self.filename)
        announce = metainfo['announce']
        info = metainfo['info']
        info_hash = hashlib.sha1(bencode.bencode(info))

        total_size = data_size(metainfo)
        piece_length = info['piece length']
        piece_number, last_piece_length = divmod(total_size, piece_length)

        # Build result
        result = [
            "NAME %s" % (os.path.basename(self.filename)),
            "SIZE %s (%i * %s + %s)" % (
                fmt.human_size(total_size).strip(),
                piece_number, fmt.human_size(piece_length).strip(),
                fmt.human_size(last_piece_length).strip(),
            ),
            "HASH %s" % (info_hash.hexdigest().upper()),
            "URL  %s" % (mask_keys if masked else str)(announce),
            "PRV  %s" % ("YES (DHT/PEX disabled)" if info.get("private") else "NO (DHT/PEX enabled)"),
            "TIME %s" % ("N/A" if "creation date" not in metainfo else
                time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(metainfo["creation date"]))
            ),
        ]
        
        for label, key in (("BY  ", "created by"), ("REM ", "comment")):
            if key in metainfo:
                result.append("%s %s" % (label, metainfo[key]))
                
        result.extend([
            "",
            "FILE LISTING",
        ])
        if info.has_key('length'):
            # Single file
            result.append("%-69s%9s" % (
                    info['name'],
                    fmt.human_size(total_size),
            ))
        else:
            # Directory structure
            result.append("%s/" % info['name'])
            oldpaths = [None] * 99
            for entry in info['files']:
                for idx, item in enumerate(entry['path'][:-1]):
                    if item != oldpaths[idx]:
                        result.append("%s%s/" % (' ' * (4*(idx+1)), item))
                        oldpaths[idx] = item
                result.append("%-69s%9s" % (
                    ' ' * (4*len(entry['path'])) + entry['path'][-1],
                    fmt.human_size(entry['length']),
                ))

        return result

