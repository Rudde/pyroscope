# -*- coding: utf-8 -*-
# pylint: disable=I0011
""" rTorrent web apps.

    Copyright (c) 2013 The PyroScope Project <pyroscope.project@gmail.com>
"""
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along
# with this program; if not, write to the Free Software Foundation, Inc.,
# 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.
import os
import re
import json
import time
import socket
import logging
import mimetypes

import psutil

from webob import exc, static, Request, Response
from webob.dec import wsgify
#from webob.response import Response

from pyrobase.parts import Bunch
from pyrocore import config, error
from pyrocore.util import pymagic, xmlrpc


# Default paths to serve static file from
HTDOCS_PATHS = [
    os.path.realpath(os.path.join(config.config_dir, "htdocs")),
    os.path.join(os.path.dirname(config.__file__), "data", "htdocs"),
]


class StaticFolders(object):
    """ An application that serves up the files in a list of given directories.

        Non-existent paths are ignored.
        Pass a `fileapp` factory to change the default file serving app.
    """

    def __init__(self, paths, fileapp=None, **kw):
        self.LOG = pymagic.get_class_logger(self)
        self.paths = []
        self.fileapp = fileapp or static.FileApp
        self.fileapp_kw = kw
        
        for path in paths:
            path = os.path.abspath(path).rstrip(os.path.sep) + os.path.sep
            if os.path.isdir(path):
                self.paths.append(path)
            else:
                self.LOG.warn("Static HTTP directory %r not found, ignoring it" % path)


    @wsgify
    def __call__(self, req):
        urlpath = req.urlvars.filepath.strip('/').replace("..", "!FORBIDDEN!")
    
        for basepath in self.paths:
            path = os.path.abspath(os.path.realpath(os.path.join(basepath, urlpath)))
            if not os.path.isfile(path):
                continue
            elif not path.startswith(basepath):
                return exc.HTTPForbidden(comment="Won't follow symlink to %r" % urlpath)
            else:
                return self.fileapp(path, **self.fileapp_kw)

        return exc.HTTPNotFound(comment=urlpath)


class JsonController(object):
    """ Controller for generating JSON data.
    """
    
    def __init__(self, **kwargs):
        self.LOG = pymagic.get_class_logger(self)
        self.cfg = Bunch(kwargs)


    @wsgify
    def __call__(self, req):
        action = req.urlvars.get("action")
        try:
            try:
                method = getattr(self, "json_" + action)
            except AttributeError:
                raise exc.HTTPNotFound("No action '%s'" % action)

            resp = method(req)

            if isinstance(resp, (dict, list)):
                try:
                    resp = json.dumps(resp, sort_keys=True)
                except (TypeError, ValueError, IndexError, AttributeError), json_exc:
                    raise exc.HTTPInternalServerError("JSON serialization error (%s)" % json_exc)
            if isinstance(resp, basestring):
                resp = Response(body=resp, content_type="application/json")
        except exc.HTTPException, http_exc:
            resp = http_exc
        return resp


    def json_engine(self, req):
        """ Return torrent engine data.
        """
        try:
            proxy = config.engine.open()

            data = dict(
                now         = time.time(),
                engine_id   = config.engine.engine_id,
                versions    = config.engine.versions,
                uptime      = config.engine.uptime,
                upload      = [proxy.get_up_rate(), proxy.get_upload_rate()],
                download    = [proxy.get_down_rate(), proxy.get_download_rate()],
                views       = dict([(name, proxy.view.size('', name))
                    for name in ("main", "started", "stopped", "complete", "incomplete", "seeding", "leeching", "active", "messages")
                ]),
            )
            return data
        except (error.LoggableError, xmlrpc.ERRORS), torrent_exc:
            raise exc.HTTPInternalServerError(str(torrent_exc))


    def json_charts(self, req):
        """ Return charting data.
        """
        try:
            disk_usage = psutil.disk_usage(os.path.expanduser(self.cfg.disk_usage_path))
            disk_usage = (disk_usage.used, disk_usage.total)
        except OSError:
            disk_usage = (None, None)

        data = dict(
            engine      = self.json_engine(req),
            uptime      = time.time() - psutil.BOOT_TIME,
            fqdn        = socket.getfqdn(),
            cpu_usage   = psutil.cpu_percent(0),
            ram_usage   = psutil.virtual_memory(),
            swap_usage  = psutil.swap_memory(),
            disk_usage  = disk_usage,
            disk_io     = psutil.disk_io_counters(),
            net_io      = psutil.network_io_counters(),
        )
        return data


class Router(object):
    """ URL router middleware.
    
        See http://docs.webob.org/en/latest/do-it-yourself.html
    """

    ROUTES_RE = re.compile(r'''
        \{              # The exact character "{"
        (\w+)           # The variable name (restricted to a-z, 0-9, _)
        (?::([^}]+))?   # The optional :regex part
        \}              # The exact character "}"
        ''', re.VERBOSE)


    @classmethod
    def parse_route(cls, template):
        regex = ''
        last_pos = 0

        for match in cls.ROUTES_RE.finditer(template):
            regex += re.escape(template[last_pos:match.start()])
            var_name = match.group(1)
            expr = match.group(2) or '[^/]+'
            expr = '(?P<%s>%s)' % (var_name, expr)
            regex += expr
            last_pos = match.end()

        regex += re.escape(template[last_pos:])
        regex = '^%s$' % regex

        return re.compile(regex)


    def __init__(self):
        self.LOG = pymagic.get_class_logger(self)
        self.routes = []

 
    def add_route(self, template, controller, **kwargs):
        if isinstance(controller, basestring):
            controller = pymagic.import_name(controller)

        self.routes.append((self.parse_route(template), controller, kwargs))

        return self


    def __call__(self, environ, start_response):
        req = Request(environ)
        self.LOG.debug("Incoming request at %r" % (req.path_info,))

        for regex, controller, kwargs in self.routes:
            match = regex.match(req.path_info)
            if match:
                req.urlvars = Bunch(kwargs)
                req.urlvars.update(match.groupdict())
                self.LOG.debug("controller=%r; vars=%r; req=%r; env=%r" % (controller, req.urlvars, req, environ))
                return controller(environ, start_response)

        return exc.HTTPNotFound()(environ, start_response)


@wsgify
def redirect(req, _log=logging.getLogger("redirect")):
    log = req.environ.get("wsgilog.logger", _log)
    to = req.relative_url(req.urlvars.to)
    log.info("Redirecting '%s' to '%s'" % (req.url, to))
    return exc.HTTPMovedPermanently(location=to)


def make_app(httpd_config):
    """ Factory for the monitoring webapp.
    """
    #mimetypes.add_type('image/vnd.microsoft.icon', '.ico')
    
    return (Router()
        #.add_route("/", controller=index, **httpd_config.index)
        #.add_route("/", controller=static.FileApp(os.path.join(HTDOCS_PATHS[0], "index.html")))
        .add_route("/", controller=redirect, to="/static/index.html")
        #.add_route("/favicon.ico", controller=static.FileApp(os.path.join(HTDOCS_PATHS[-1], "favicon.ico")))
        .add_route("/favicon.ico", controller=redirect, to="/static/favicon.ico")
        .add_route("/static/{filepath:.+}", controller=StaticFolders(HTDOCS_PATHS))
        .add_route("/json/{action}", controller=JsonController(**httpd_config.json))
    )

