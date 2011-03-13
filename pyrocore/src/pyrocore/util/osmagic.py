# -*- coding: utf-8 -*-
# pylint: disable=I0011
""" PyroCore - Platform Specific Incantations.

    Copyright (c) 2011 The PyroScope Project <pyroscope.project@gmail.com>

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
import os
import sys
import time
import signal
import logging


def daemonize(pidfile=None, sync=True):
    """ Fork the process into the background.
    
        @param pidfile: Optional PID file path.
        @param sync: Wait for parent process to disappear?  
    """
    log = logging.getLogger(__name__)
    ppid = os.getpid()

    try:
        pid = os.fork()
        if pid > 0:
            log.debug("Parent exiting (PID %d)" % os.getpid())
            sys.exit(0)
    except OSError, e:
        log.critical("fork #1 failed: (%d) %s\n" % (e.errno, e.strerror))
        sys.exit(1)

    ##os.chdir("/")
    ##os.umask(0022)
    os.setsid()

    try:
        pid = os.fork()
        if pid > 0:
            log.debug("Session leader exiting (PID %d)" % os.getpid())
            sys.exit(0)
    except OSError, e:
        log.critical("fork #2 failed: (%d) %s\n" % (e.errno, e.strerror))
        sys.exit(1)

    if pidfile:
        pid = str(os.getpid())
        handle = open(pidfile, 'w')
        try:
            handle.write("%s\n" % pid)
        finally:
            handle.close()

    def sig_term(*dummy):
        "Handler for SIGTERM."
        sys.exit(0)

    stdin = open("/dev/null", "r")
    os.dup2(stdin.fileno(), sys.stdin.fileno())
    signal.signal(signal.SIGTERM, sig_term)

    if sync:
        # Wait for 5 seconds at most, in 10ms steps
        polling = 5, .01
        for _ in range(int(polling[0] * 1 / polling[1])):
            try:
                os.kill(ppid, 0)
            except OSError:
                break
            else:
                time.sleep(polling[1])

    log.debug("Process detached (PID %d)" % os.getpid())
