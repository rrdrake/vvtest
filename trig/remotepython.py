
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
                       sshcmd='ssh',
                       logfile=None ):
        ""
        self.started = False

        logfp = _check_open_logfile( logfile )

        self.inp = InputHandler( logfp )
        self.out = OutputHandler( logfp, 'OUT' )
        self.err = OutputHandler( logfp, 'ERR' )

        self.cmdL = bootstrap_command( pythonexe, machine, sshcmd )

        self.sub = launch_bootstrap( self.cmdL,
                                     self.inp.getReadFileDescriptor(),
                                     self.out.getWriteFileDescriptor(),
                                     self.err.getWriteFileDescriptor(),
                                     logfp )

        self.inp.begin()
        self.out.begin()
        self.err.begin()

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
            return self.sub.poll() == None
        return False

    def close(self):
        ""
        if self.sub != None:

            self.inp.close()

            if self.sub.poll() == None:
                self.sub.terminate()

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


class OutputHandler( threading.Thread ):

    def __init__(self, logfp, logprefix):
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

        fdr, self.fdw = os.pipe()
        self.fp = os.fdopen( fdr )

        self.logfp = logfp
        self.logprefix = logprefix

    def getWriteFileDescriptor(self):
        ""
        return self.fdw

    def begin(self):
        ""
        os.close( self.fdw )
        self.start()

    def run(self):
        ""
        while True:
            try:
                line = self.fp.readline()
            except Exception:
                break

            if line:
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

    def getLine(self):
        ""
        val = None
        with self.lck:
            if len( self.lines ) > 0:
                val = self.lines.popleft()
        return val


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


class InputHandler:

    def __init__(self, logfp=None):
        ""
        self.fdr, self.fdw = os.pipe()

        self.logfp = logfp

    def getReadFileDescriptor(self):
        ""
        return self.fdr

    def begin(self):
        ""
        os.close( self.fdr )

    def write(self, data):
        ""
        if self.logfp != None:
            self._write_to_log( data )
        write_to_fd( self.fdw, repr(data)+'\n' )

    def _write_to_log(self, data):
        ""
        self.logfp.write( 'SND: ' )
        for idx,line in enumerate( data.splitlines() ):
            if idx > 0:
                self.logfp.write( '%3d: '%(idx+1) )
            self.logfp.write( line )
            self.logfp.write( '\n' )
        self.logfp.flush()

    def close(self):
        ""
        try:
            write_to_fd( self.fdw, repr('raise SystemExit()')+'\n' )
        except Exception:
            pass

        try:
            os.close( self.fdw )
        except Exception:
            pass


if sys.version_info[0] < 3:
    def write_to_fd( fd, buf ):
        ""
        os.write( fd, buf )

else:
    bytes_type = type( ''.encode() )

    def write_to_fd( fd, buf ):
        ""
        if type(buf) != bytes_type:
            buf = buf.encode( 'utf-8' )
        os.write( fd, buf )


def bootstrap_command( pythonexe, machine, sshcmd ):
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

    if machine:
        remote_cmd = ' '.join( [ pipes.quote( arg ) for arg in cmdL ] )
        cmdL = shlex.split( sshcmd )
        cmdL.extend( [ machine, remote_cmd ] )

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
    _remotepython_eval_count += 1
    filename = "<remotecode"+str(_remotepython_eval_count)+">"
    _remotepython_linecache[ filename ] = lines.splitlines()
    return filename
"""

bootstrap_waitloop = """
line = sys.stdin.readline()
while line:
    lines = eval( line.strip() )
    filename = _remotepython_add_eval_linecache( lines )
    try:
        eval( compile( lines, filename, "exec" ) )
    except Exception:
        traceback.print_exc()
        sys.exit(1)
    line = sys.stdin.readline()
"""


popen_thread_lock = threading.Lock()

def launch_bootstrap( cmdL, in_r, out_w, err_w, logfp ):
    """
    Older subprocess modules are known to have thread safety problems.  Use a
    thread lock on the Popen call to avoid most issues.
    """
    if logfp != None:
        logfp.write( 'CMD: '+str(cmdL)+'\n' )
        logfp.flush()

    with popen_thread_lock:
        proc = subprocess.Popen( cmdL, stdin=in_r, stdout=out_w,
                                       stderr=err_w, bufsize=0 )

    return proc
