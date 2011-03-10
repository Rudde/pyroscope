# -*- coding: utf-8 -*-
# pylint: disable=I0011
""" PyroCore - rTorrent Proxy.

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

import time
import socket
import fnmatch
import operator
import xmlrpclib
from contextlib import closing

from pyrocore import config, error
from pyrocore.util import os, xmlrpc2scgi, load_config, types, traits, fmt
from pyrocore.torrent import engine


class RtorrentItem(engine.TorrentProxy):
    """ A single download item.
    """

    def __init__(self, engine, fields):
        """ Initialize download item.
        """
        super(RtorrentItem, self).__init__()
        self._engine = engine
        self._fields = dict(fields)


    def _make_it_so(self, command, calls, *args):
        """ Perform some error-checked XMLRPC calls.
        """
        args = (self._fields["hash"],) + args
        try:
            for call in calls:
                self._engine.LOG.debug("%s%s torrent #%s (%s)" % (
                    command[0].upper(), command[1:], self._fields["hash"], call))
                getattr(self._engine._rpc.d, call)(*args)
        except xmlrpclib.Fault, exc:
            raise error.EngineError("While %s torrent #%s: %s" % (command, self._fields["hash"], exc))


    def _get_files(self, attrs=None):
        """ Get a list of all files in this download; each entry has the
            attributes C{path} (relative to root), C{size} (in bytes),
            C{mtime}, C{priority} (0=off, 1=normal, 2=high), C{created}, 
            and C{opened}.
            
            This is UNCACHED, use C{fetch("files")} instead.
            
            @param attrs: Optional list of additional attributes to fetch. 
        """
        try:
            # Get info for all files
            f_multicall = self._engine._rpc.f.multicall
            f_params = [self._fields["hash"], 0,
                "f.get_path=", "f.get_size_bytes=", "f.get_last_touched=",
                "f.get_priority=", "f.is_created=", "f.is_open=",
            ]
            for attr in (attrs or []):
                f_params.append("f.%s=" % attr)
            rpc_result = f_multicall(*tuple(f_params))
        except xmlrpclib.Fault, exc:
            raise error.EngineError("While %s torrent #%s: %s" % (
                "getting files for", self._fields["hash"], exc))
        else:
            #self._engine.LOG.debug("files result: %r" % rpc_result)

            # Return results
            result = [types.Bunch(
                path=i[0], size=i[1], mtime=i[2] / 1000000.0,
                prio=i[3], created=i[4], opened=i[5],
            ) for i in rpc_result]

            if attrs:
                for idx, attr in enumerate(attrs):
                    if attr.startswith("get_"):
                        attr = attr[4:]
                    for item, rpc_item in zip(result, rpc_result):
                        item[attr] = rpc_item[6+idx]

            return result


    def _get_kind(self, limit):
        """ Get a set of dominant file types. The files must contribute
            at least C{limit}% to the item's total size.
        """
        histo = self.fetch("custom_kind")

        if histo:
            # Parse histogram from cached field
            histo = [i.split("%_") for i in histo.split()]
            histo = [(int(val, 10), ext) for val, ext in histo]
            ##self._engine.LOG.debug("~~~~~~~~~~ cached histo = %r" % histo)
        else:
            # Get filetypes
            histo = traits.get_filetypes(self.fetch("files"),
                path=operator.attrgetter("path"), size=operator.attrgetter("size"))

            # Set custom cache field with value formatted like "80%_flac 20%_jpg" (sorted by percentage)
            histo_str = ' '.join(("%d%%_%s" % i).replace(' ', '_') for i in histo)
            self._make_it_so("setting kind cache %r on" % (histo_str,), ["set_custom"], "kind", histo_str)
            self._fields["custom_kind"] = histo_str

        # Return all non-empty extensions that make up at least <limit>% of total size
        return set(ext for val, ext in histo if ext and val >= limit)


    def fetch(self, name, engine_name=None):
        """ Get a field on demand.
        """
        # TODO: Get each on-demand field in a multicall for all other items, since
        # we likely need it anyway; another (more easy) way would be to pre-fetch dynamically
        # with the list of fields from filters and output formats
        try:
            return self._fields[name]
        except KeyError:
            if name == "done":
                val = float(self.fetch("completed_chunks")) / self.fetch("size_chunks")
            elif name == "files":
                val = self._get_files()
            elif name.startswith("kind_") and name[5:].isdigit():
                val = self._get_kind(int(name[5:], 10))
            elif name.startswith("custom_"):
                key = name[7:]
                try:
                    if len(key) == 1 and key in "12345":
                        val = getattr(self._engine._rpc.d, "get_custom"+key)(self._fields["hash"])
                    else:
                        val = self._engine._rpc.d.get_custom(self._fields["hash"], key)
                except xmlrpclib.Fault, exc:
                    raise error.EngineError("While accessing field %r: %s" % (name, exc))
            else:
                getter_name = engine_name if engine_name else RtorrentEngine.PYRO2RT_MAPPING.get(name, name)
                if getter_name[0] == '=':
                    getter_name = getter_name[1:]
                else:
                    getter_name = "get_" + getter_name
                getter = getattr(self._engine._rpc.d, getter_name)
    
                try:
                    val = getter(self._fields["hash"])
                except xmlrpclib.Fault, exc:
                    raise error.EngineError("While accessing field %r: %s" % (name, exc))

            # TODO: Currently, NOT caching makes no sense; in a demon, it does!
            #if isinstance(FieldDefinition.FIELDS.get(name), engine.ConstantField):
            self._fields[name] = val

            return val


    def announce_urls(self):
        """ Get a list of all announce URLs.
        """
        try:
            return [self._engine._rpc.t.get_url(self._fields["hash"], i) for i in range(self._fields["tracker_size"])]
        except xmlrpclib.Fault, exc:
            raise error.EngineError("While getting announce URLs for #%s: %s" % (self._fields["hash"], exc))


    def start(self):
        """ (Re-)start downloading or seeding.
        """
        self._make_it_so("starting", ["open", "start"])


    def stop(self):
        """ Stop and close download.
        """
        self._make_it_so("stopping", ["stop", "close"])


    def ignore(self, flag):
        """ Set ignore status.
        """
        self._make_it_so("setting ignore status for", ["set_ignore_commands"], int(flag))


    def tag(self, tags):
        """ Add or remove tags.
        """
        # Get tag list and add/remove given tags
        tags = tags.lower()
        previous = self.tagged
        tagset = previous.copy()
        for tag in tags.split():
            if tag.startswith('-'):
                tagset.discard(tag[1:])
            elif tag.startswith('+'):
                tagset.add(tag[1:])
            else:
                tagset.add(tag)

        # Write back new tagset, if changed
        tagset.discard('')
        if tagset != previous:
            tagset = ' '.join(sorted(tagset))
            self._make_it_so("setting tags %r on" % (tagset,), ["set_custom"], "tags", tagset)
            self._fields["custom_tags"] = tagset


    def set_throttle(self, name):
        """ Assign to throttle group.
        """
        if name.lower() == "null":
            name = "NULL"
        if name.lower() == "none":
            name = ""

        if (name or "NONE") not in config.throttle_names:
            raise error.UserError("Unknown throttle name %r" % (name or "NONE",))

        if (name or "NONE") == self.throttle:
            self._engine.LOG.debug("Keeping throttle %r on torrent #%s" % (self.throttle, self._fields["hash"]))
            return

        active = self.is_active
        if active:
            self._engine.LOG.debug("Torrent #%s stopped for throttling" % (self._fields["hash"],))
            self.stop()
        self._make_it_so("setting throttle %r on" % (name,), ["set_throttle_name"], name)
        if active:
            self._engine.LOG.debug("Torrent #%s restarted after throttling" % (self._fields["hash"],))
            self.start()


    def set_custom(self, key, value=None):
        """ Set a custom value. C{key} might have the form "key=value" when value is C{None}.
        """
        # Split combined key/value
        if value is None:
            try:
                key, value = key.split('=', 1)
            except (ValueError, TypeError), exc:
                raise error.UserError("Bad custom field assignment %r, probably missing a '=' (%s)" % (key, exc))

        # Check identifier rules
        if not key:
            raise error.UserError("Custom field name cannot be empty!")
        elif len(key) == 1 and key in "12345":
            method, args = "set_custom"+key, (value,)
        elif not (key[0].isalpha() and key.replace("_", "").isalnum()):
            raise error.UserError("Bad custom field name %r (must only contain a-z, A-Z, 0-9 and _)" % (key,))
        else:
            method, args = "set_custom", (key, value)

        # Make the assignment                    
        self._make_it_so("setting custom_%s = %r on" % (key, value), [method], *args)
        self._fields["custom_"+key] = value
        

    def hash_check(self):
        """ Hash check a download.
        """
        self._make_it_so("hash-checking", ["check_hash"])


    def delete(self):
        """ Remove torrent from client.
        """
        self.stop()
        self._make_it_so("removing metafile of", ["delete_tied"])
        self._make_it_so("erasing", ["erase"])


    def purge(self):
        """ Delete PARTIAL data files and remove torrent from client.
        """
        def partial_file(item):
            "Filter out partial files"
            #print "???", repr(item)
            return item.completed_chunks < item.size_chunks
            
        self.cull(file_filter=partial_file, attrs=["get_completed_chunks", "get_size_chunks"])

    
    def cull(self, file_filter=None, attrs=None):
        """ Delete ALL data files and remove torrent from client.

            @param file_filter: Optional callable for selecting a subset of all files.
                The callable gets a file item as described for RtorrentItem._get_files
                and must return True for items eligible for deletion. 
            @param attrs: Optional list of additional attributes to fetch for a filter. 
        """
        dry_run = 0
        
        def remove_with_links(path):
            "Remove a path including any symlink chains leading to it."
            rm_paths = []
            while os.path.islink(path):
                target = os.readlink(path)
                rm_paths.append(path)
                path = target

            if os.path.exists(path):
                rm_paths.append(path)
            
            # Remove the link chain, starting at the real path
            # (this prevents losing the chain when there's permission problems)
            for path in reversed(rm_paths):
                is_dir = os.path.isdir(path)
                self._engine.LOG.debug("Deleting '%s%s'" % (path, '/' if is_dir else ''))
                if not dry_run:
                    (os.rmdir if is_dir else os.remove)(path)
        
            return rm_paths
        
        # Assemble doomed files and directories
        files, dirs = set(), set()
        if not os.path.isdir(self.path):
            files.add(self.path)
        else:
            dirs.add(self.path)

            for item in self._get_files(attrs=attrs):
                if file_filter and not file_filter(item):
                    continue
                #print repr(item)
                path = os.path.join(self.path, item.path)
                files.add(path)
                if '/' in item.path:
                    dirs.add(os.path.dirname(path))
        
        # Delete selected files
        if not dry_run:
            self.stop()
        for path in sorted(files):
            ##self._engine.LOG.debug("Deleting file '%s'" % (path,))
            remove_with_links(path)
        
        # Prune empty directories (longer paths first)
        doomed = files | dirs
        for path in sorted(dirs, reverse=True):
            residue = set(os.listdir(path) if os.path.exists(path) else [])
            ignorable = set(i for i in residue 
                if any(fnmatch.fnmatch(i, pat) for pat in config.waif_pattern_list)
                #or os.path.join(path, i) in doomed 
            )
            ##print "---", residue - ignorable
            if residue and residue != ignorable:
                self._engine.LOG.info("Keeping non-empty directory '%s' with %d %s%s!" % (
                    path, len(residue),
                    "entry" if len(residue) == 1 else "entries",
                    (" (%d ignorable)" % len(ignorable)) if ignorable else "",
                ))
            else:
                ##print "---", ignorable
                for waif in ignorable - doomed:
                    waif = os.path.join(path, waif)
                    self._engine.LOG.debug("Deleting waif '%s'" % (waif,))
                    if not dry_run:
                        os.remove(waif)
                    
                ##self._engine.LOG.debug("Deleting empty directory '%s'" % (path,))
                doomed.update(remove_with_links(path))
        
        # Delete item from engine
        if not dry_run:
            self.delete()


    def flush(self):
        """ Write volatile data to disk.
        """
        self._make_it_so("saving session data of", ["save_session"])


class RtorrentEngine(engine.TorrentEngine):
    """ The rTorrent backend proxy.
    """
    # throttling config keys
    RTORRENT_RC_THROTTLE_KEYS = ("throttle_up", "throttle_down", "throttle_ip", )

    # keys we read from rTorrent's configuration
    RTORRENT_RC_KEYS = ("scgi_local", "scgi_port", ) + RTORRENT_RC_THROTTLE_KEYS

    # rTorrent names of fields that never change
    CONSTANT_FIELDS = set((
        "hash", "name", "is_private", "tracker_size", "size_bytes", 
    ))

    # rTorrent names of fields that need to be pre-fetched
    CORE_FIELDS = CONSTANT_FIELDS | set((
        "complete", "tied_to_file",
    ))

    # rTorrent names of fields that get fetched in multi-call
    PREFETCH_FIELDS = CORE_FIELDS | set((
        "is_open", "is_active",
        "ratio", "up_rate", "up_total", "down_rate", "down_total",
        "base_path",  
    ))

    # mapping of our names to rTorrent names (only those that differ)
    PYRO2RT_MAPPING = dict(
        is_complete = "complete",
        is_ignored = "ignore_commands",
        down = "down_rate",
        up = "up_rate",
        path = "base_path", 
        metafile = "tied_to_file", 
        size = "size_bytes",
        prio = "priority",
        throttle = "throttle_name",
    )

    # inverse mapping of rTorrent names to ours
    RT2PYRO_MAPPING = dict((v, k) for k, v in PYRO2RT_MAPPING.items()) 


    def __init__(self):
        """ Initialize proxy.
        """
        super(RtorrentEngine, self).__init__()
        self._rpc = None
        self._session_dir = None
        self._download_dir = None
        self._item_cache = {}


    def _load_rtorrent_rc(self, namespace, rtorrent_rc=None):
        """ Load file given in "rtorrent_rc".
        """
        # Only load when needed (also prevents multiple loading)
        if not all(getattr(namespace, key, False) for key in self.RTORRENT_RC_KEYS):
            # Get and check config file name
            if not rtorrent_rc:
                rtorrent_rc = getattr(config, "rtorrent_rc", None)
            if not rtorrent_rc:
                raise error.UserError("No 'rtorrent_rc' path defined in configuration!")
            if not os.path.isfile(rtorrent_rc):
                raise error.UserError("Config file %r doesn't exist!" % (rtorrent_rc,))

            # Parse the file
            self.LOG.debug("Loading rtorrent config from %r" % (rtorrent_rc,))
            with closing(open(rtorrent_rc)) as handle:
                for line in handle.readlines():
                    # Skip comments and empty lines
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue

                    # Be lenient about errors, after all it's not our own config file
                    try:
                        key, val = line.split("=", 1)
                    except ValueError:
                        self.LOG.warning("Ignored invalid line %r in %r!" % (line, rtorrent_rc))
                        continue
                    key, val = key.strip(), val.strip()

                    # Copy values we're interested in
                    if key in self.RTORRENT_RC_THROTTLE_KEYS:
                        val = val.split(',')[0].strip()
                        self.LOG.debug("rtorrent.rc: added throttle %r" % (val,))
                        namespace.throttle_names.add(val)
                    elif key in self.RTORRENT_RC_KEYS and not getattr(namespace, key, None):
                        self.LOG.debug("rtorrent.rc: %s = %s" % (key, val))
                        setattr(namespace, key, val)

        # Validate fields
        for key in self.RTORRENT_RC_KEYS:
            setattr(namespace, key, load_config.validate(key, getattr(namespace, key, None)))
        if config.scgi_local and config.scgi_local.startswith("/"):
            config.scgi_local = "scgi://" + config.scgi_local
        if config.scgi_port and not config.scgi_port.startswith("scgi://"):
            config.scgi_port = "scgi://" + config.scgi_port

        # Prefer UNIX domain sockets over TCP sockets
        config.scgi_url = config.scgi_local or config.scgi_port


    def __repr__(self):
        """ Return a representation of internal state.
        """
        if self._rpc:
            # Connected state
            return "%s connected to %s [%s, up %s] via %r" % (
                self.__class__.__name__, self.engine_id, self.engine_software,
                fmt.human_duration(self.uptime, 0, 2, True).strip(), config.scgi_url,
            )
        else:
            # Unconnected state
            self._load_rtorrent_rc(config)
            return "%s connectable via %r" % (
                self.__class__.__name__, config.scgi_url,
            )


    @property
    def uptime(self):
        """ rTorrent's uptime.
        """
        return time.time() - self.startup


    def open(self):
        """ Open connection.
        """
        # Only connect once
        if self._rpc is not None:
            return self._rpc

        # Get connection URL from rtorrent.rc
        self._load_rtorrent_rc(config)

        # Reading abilities are on the downfall, so...
        if not config.scgi_url:
            raise error.UserError("You need to configure a XMLRPC connection, read"
                " http://code.google.com/p/pyroscope/wiki/UserConfiguration")

        # Connect and get instance ID (also ensures we're connectable)
        self._rpc = xmlrpc2scgi.RTorrentProxy(config.scgi_url)
        try:
            self.engine_id = self._rpc.get_name()
            time_usec = self._rpc.system.time_usec()
        except socket.error, exc:
            raise error.LoggableError("Can't connect to %s (%s)" % (config.scgi_url, exc))
        except Exception, exc:
            raise error.LoggableError("Can't connect to %s (%s)" % (config.scgi_url, exc))

        # Make sure xmlrpc-c works as expected
        if time_usec < 2**32:
            self.LOG.warn("Your xmlrpc-c is broken (64 bit integer support missing,"
                " %r returned instead)" % (type(time_usec),))

        # Get other manifest values
        self.engine_software = "rTorrent %s/%s" % (
            self._rpc.system.client_version(), self._rpc.system.library_version(),
        )
        self._session_dir = self._rpc.get_session()
        if not self._session_dir:
            raise error.UserError("You need a session directory, read"
                " http://code.google.com/p/pyroscope/wiki/UserConfiguration")
        if not os.path.exists(self._session_dir):
            raise error.UserError("Non-existing session directory %r" % self._session_dir)
        self._download_dir = os.path.expanduser(self._rpc.get_directory())
        if not os.path.exists(self._download_dir):
            raise error.UserError("Non-existing download directory %r" % self._download_dir)
        self.startup = os.path.getmtime(os.path.join(self._session_dir, "rtorrent.lock"))

        # Return connection
        self.LOG.debug(repr(self))
        return self._rpc


    def items(self, view=None, prefetch=None):
        """ Get list of download items.
        """
        # TODO: Cache should be by hash.
        # Then get the initial data when cache is empty,
        # else get a list of hashes from the view, make a diff
        # to what's in the cache, fetch the rest. Getting the
        # fields for one hash might be done by a special view
        # (filter: $d.get_hash == hashvalue)
        
        if view is None:
            view = engine.TorrentView(self, "main")

        if view.viewname not in self._item_cache:
            # Map pyroscope names to rTorrent ones
            if prefetch:
                prefetch = self.CORE_FIELDS | set((self.PYRO2RT_MAPPING.get(i, i) for i in prefetch))
            else:
                prefetch = self.PREFETCH_FIELDS

            # Prepare multi-call arguments
            args = [view.viewname] + ["d.%s%s=" % (
                    "" if field.startswith("is_") else "get_", field
                ) for field in prefetch
            ]

            # Fetch items
            items = []
            try:
                ##self.LOG.debug("multicall %r" % (args,))
                multi_call = self.open().d.multicall
                raw_items = multi_call(*tuple(args))
                ##import pprint; self.LOG.debug(pprint.pformat(raw_items))
                self.LOG.debug("Got %d items with %d attributes from %r [%s]" % (
                    len(raw_items), len(prefetch), self.engine_id, multi_call))

                for item in raw_items:
                    items.append(RtorrentItem(self, zip(
                        [self.RT2PYRO_MAPPING.get(i, i) for i in prefetch], item
                    )))
                    yield items[-1]
            except xmlrpclib.Fault, exc:
                raise error.EngineError("While getting download items from %r: %s" % (self, exc))

            # Everything yielded, store for next iteration
            self._item_cache[view.viewname] = items
        else:
            # Yield prefetched results
            for item in self._item_cache[view.viewname]:
                yield item

    def show(self, items, view=None):
        """ Visualize a set of items (search result).
        """
        proxy = self.open()
        view = view or "rtcontrol"
        
        # Add view if needed
        if view not in proxy.view_list():
            proxy.view_add(view)
        
        # Clear view and show it
        proxy.view_filter(view, "false=")
        proxy.ui.current_view.set(view)

        # Add items
        # TODO: should be a "system.multicall"
        for item in items:
            proxy.view.set_visible(item.hash, view)
