#!/usr/bin/env python

# Copyright 2018 National Technology & Engineering Solutions of Sandia, LLC
# (NTESS). Under the terms of Contract DE-NA0003525 with NTESS, the U.S.
# Government retains certain rights in this software.

import os, sys
import threading
import pipes
import subprocess
import inspect
import time
import collections
import shlex


class RemotePython:

    def __init__(self, machine=None,
                       pythonexe='python',
                       sshcmd='ssh -t -t',
                       bashlogin=False,
                       logfile=None ):
        """
        The 'sshcmd' is the path to ssh with any options. The options -t -t
        are used to ensure remote subprocesses receive a SIGHUP/SIGTERM.
        """
        self.started = False

        logfp = _check_open_logfile( logfile )

        self.cmdL = bootstrap_command( pythonexe, machine, sshcmd, bashlogin )

        if logfp != None:
            logfp.write( 'CMD: '+str(self.cmdL)+'\n' )
            logfp.flush()

        self.sub = RemoteProcess( self.cmdL )

        self.inp = ReprWriter( self.sub.getStdIn(), logfp )
        self.out = AsynchronousReader( self.sub.getStdOut(), logfp, 'OUT' )
        self.err = AsynchronousReader( self.sub.getStdErr(), logfp, 'ERR' )

        self.connbuf = ''

    def start(self, timeout=30):
        """
        Returns True if a successful connection has been made.  Either
        way, the communication made during startup is available with
        getStartupOutput().
        """
        self.started = True
        self.execute( bootstrap_preamble+bootstrap_waitloop )
        ok = self._verify_connection( timeout )
        return ok

    def getStartupOutput(self):
        ""
        return self.connbuf

    def execute(self, *lines):
        ""
        assert self.started, "connection not started"
        if lines:
            self.inp.write( '\n'.join(lines) )

    def addModule(self, modname, *lines):
        ""
        assert self.started, "connection not started"
        assert modname and len(lines) > 0
        self.inp.write( '_remotepython_add_module( ' + \
                                repr(modname)+',' + \
                                repr('\n'.join(lines))+' )' )

    def getOutputLine(self):
        ""
        return self.out.getLine()

    def getErrorLine(self):
        ""
        return self.err.getLine()

    def isAlive(self):
        ""
        if self.sub != None:
            return self.sub.isAlive()
        return False

    def close(self):
        ""
        if self.sub != None:
            self.sub.close()
            self.inp = None
            self.sub = None

    def _verify_connection(self, timeout):
        ""
        mark = 'RemotePython'+str(id(self))
        self.execute( 'print ("'+mark+'")' )

        ok, buf = self._wait_for_mark( mark, timeout )

        if not ok:
            self.close()

        self.connbuf = buf + \
                       flush_lines( self.out ) + \
                       flush_lines( self.err )

        return ok

    def _wait_for_mark(self, mark, timeout):
        ""
        tstart = time.time()
        ok = False
        buf = ''

        while True:

            if time.time()-tstart > timeout:
                ok = False
                buf += 'RemotePython connection timed out: '+str(self.cmdL)
                buf += '\ntimeout value = '+str(timeout)+'\n'
                break

            ok = self.isAlive()
            if ok:
                out = self.getOutputLine()
                if out:
                    if mark in out:
                        break
                    else:
                        buf += out
            else:
                buf += 'RemotePython connection failed: '+str(self.cmdL)+'\n'
                break

        return ok, buf


def _check_open_logfile( logfile ):
    ""
    if logfile != None and type(logfile) == type(''):
        return open( logfile, 'wt' )

    return logfile


def flush_lines( handler ):
    ""
    buf = ''
    while True:
        out = handler.getLine()
        if out:
            buf += out
        else:
            break
    return buf


class ReprWriter:

    def __init__(self, outfp, logfp=None):
        ""
        self.outfp = outfp
        self.logfp = logfp

    def write(self, data):
        ""
        if self.logfp != None:
            self._write_to_log( data )

        self.outfp.write( make_bytes( repr(data)+'\n' ) )
        self.outfp.flush()

    def _write_to_log(self, data):
        ""
        self.logfp.write( 'SND: ' )

        for idx,line in enumerate( data.splitlines() ):
            if idx > 0:
                self.logfp.write( '%3d: '%(idx+1) )
            self.logfp.write( line )
            self.logfp.write( '\n' )

        self.logfp.flush()


class AsynchronousReader( threading.Thread ):

    def __init__(self, srcfp, logfp=None, logprefix='LOG'):
        ""
        threading.Thread.__init__(self)
        self.daemon = True

        # Note on reentrancy: Signals (like Ctrl-C) can cause deadlocks in
        # threading code, such as in the implementations of Queue and even
        # Condition variables.  This can manifest as a hang when you hit
        # Ctrl-C, which is unacceptable.  My solution here is to surround the
        # data structure accesses with a simple lock, which appears to be
        # reentrant.
        self.lck = threading.Lock()
        self.lines = collections.deque()

        self.fp = srcfp

        self.logfp = logfp
        self.logprefix = logprefix

        self.start()

    def getLine(self):
        ""
        val = None
        with self.lck:
            if len( self.lines ) > 0:
                val = self.lines.popleft()
        return val

    def flushLines(self):
        ""
        buf = ''

        out = self.getLine()
        while out:
            buf += out
            out = self.getLine()

        return buf

    def run(self):
        ""
        while True:
            try:
                line = self.fp.readline()
            except Exception:
                break

            if line:
                line = make_string( line )

                if self.logfp != None:
                    self._write_to_log( line )

                with self.lck:
                    self.lines.append( line )
            else:
                break

    def _write_to_log(self, line):
        ""
        try:
            self.logfp.write( self.logprefix+': '+line )
            self.logfp.flush()
        except Exception:
            pass


if sys.version_info[0] < 3:
    def make_bytes( buf ): return buf
    def make_string( buf ): return buf
else:
    def make_bytes( buf ): return buf.encode()
    def make_string( buf ): return buf.decode()


def bootstrap_command( pythonexe, machine, sshcmd, bashlogin ):
    ""
    cmdL = [
        pythonexe, '-u', '-E', '-c',
        'import sys; '
        'eval( '
            'compile( '
                'eval( sys.stdin.readline() ), '
                       '"<remotepython_from_'+os.uname()[1]+'>", '
                       '"exec" ) )'
    ]
    pycmd = ' '.join( [ pipes.quote( arg ) for arg in cmdL ] )

    if machine:
        cmdL = shlex.split( sshcmd )
        if bashlogin:
            cmdL.extend( [ machine, '/bin/bash -l -c ' + pipes.quote(pycmd) ] )
        else:
            cmdL.extend( [ machine, pycmd ] )
    elif bashlogin:
        cmdL = [ '/bin/bash', '-l', '-c', pycmd ]

    return cmdL


bootstrap_preamble = """\
import sys
sys.dont_write_bytecode = True
import traceback, linecache

_remotepython_eval_count = 0
_remotepython_linecache = {}

_remotepython_linecache_getline = linecache.getline

def _replacement_linecache_getline( filename, lineno, module_globals=None ):
    ""
    ln = _remotepython_linecache_getline( filename, lineno, module_globals )
    if not ln:
        try:
            ln = _remotepython_linecache[ filename ][lineno-1]
        except Exception:
            ln = ''
    return ln

linecache.getline = _replacement_linecache_getline

def _remotepython_add_module( modname, srclines ):
    ""
    filename = "<remotemodule_"+modname+">"
    _remotepython_linecache[ filename ] = srclines.splitlines()
    if sys.version_info[0] < 3 or sys.version_info[1] < 5:
        import imp
        mod = imp.new_module( modname )
    else:
        import importlib
        import importlib.util as imputil
        spec = imputil.spec_from_loader( modname, loader=None )
        mod = imputil.module_from_spec(spec)
    eval( compile( srclines, filename, 'exec' ), mod.__dict__ )
    sys.modules[modname] = mod

def _remotepython_add_eval_linecache( lines ):
    ""
    global _remotepython_eval_count
    linelist = lines.splitlines()
    if len(linelist) == 1 and lines.startswith( '_remotepython_' ):
        # these one liners get a generic filename to avoid line cache growth
        filename = '<remotepython>'
    else:
        _remotepython_eval_count += 1
        filename = "<remotecode"+str(_remotepython_eval_count)+">"
    _remotepython_linecache[ filename ] = linelist
    return filename

def _remotepython_eval_lines( lines ):
    ""
    try:
        filename = _remotepython_add_eval_linecache( lines )
        eval( compile( lines, filename, "exec" ), globals() )
    except Exception:
        traceback.print_exc()
        sys.exit(1)
"""

bootstrap_waitloop = """
line = sys.stdin.readline()
while line:
    lines = eval( line.strip() )
    _remotepython_eval_lines( lines )
    line = sys.stdin.readline()
"""


popen_thread_lock = threading.Lock()

class RemoteProcess:

    def __init__(self, command):
        ""
        with popen_thread_lock:
            self.subproc = subprocess.Popen( command,
                                             stdin=subprocess.PIPE,
                                             stdout=subprocess.PIPE,
                                             stderr=subprocess.PIPE )

    def getStdIn (self): return self.subproc.stdin
    def getStdOut(self): return self.subproc.stdout
    def getStdErr(self): return self.subproc.stderr

    def isAlive(self):
        ""
        if self.subproc != None:
            return self.subproc.poll() == None
        return False

    def close(self):
        ""
        if self.isAlive():
            self.subproc.terminate()
            self.subproc = None
