#!/usr/bin/env python

# Copyright 2018 National Technology & Engineering Solutions of Sandia, LLC
# (NTESS). Under the terms of Contract DE-NA0003525 with NTESS, the U.S.
# Government retains certain rights in this software.

import sys, os
import inspect
import traceback
import time
import types

from remotepython import RemotePython


class PythonProxyError( Exception ):
    pass

class FailedConnectionError( PythonProxyError ):
    pass

class RemoteExceptionError( PythonProxyError ):
    pass

class CommandTimeoutError( PythonProxyError ):
    pass

class SessionTimeoutError( PythonProxyError ):
    pass

class SerializationError( PythonProxyError ):
    pass


class PythonProxy( object ):
    """
    Uses the remotepython.RemotePython class to send python commands to a
    Python interpreter on a remote machine and return their output.

    To debug an interaction, provide a logfile to the constructor.  All
    messages to and from the remote python will be logged, including print
    statements being written by remote code.
    """

    def __init__(self, machine=None,
                       pythonexe='python',
                       sshcmd='ssh -t -t',
                       bashlogin=False,
                       logfile=None ):
        """
        If 'machine' is given, use ssh to run python on that machine.
        The 'pythonexe' is the remote python interpreter.
        The 'sshcmd' is the path to ssh with any options. The options -t -t
        are used to ensure remote subprocesses receive a SIGHUP/SIGTERM.
        If 'bashlogin' is True, run python under "/bin/bash -l" (a login shell).
        The 'logfile' can be a filename or a file-like object.
        """
        self.mach = machine
        self.sshcmd = sshcmd

        self.remote = RemotePython( machine=machine,
                                    pythonexe=pythonexe,
                                    sshcmd=sshcmd,
                                    bashlogin=bashlogin,
                                    logfile=logfile )

        self.objid = 0
        self.objs = {}
        self.endtime = None

    def get_machine_name(self): return self.mach
    def get_ssh_command(self): return self.sshcmd

    def start(self, startup_timeout=30):
        """
        Establishes the connection, or raises FailedConnectionError on failure.
        """
        err = ''

        ok = self.remote.start( startup_timeout )
        if ok:
            err = self._initialize_builtins( startup_timeout )

        if not ok or err:
            msg = ( self.remote.getStartupOutput() + '\n' + err ).rstrip()
            raise FailedConnectionError( 'startup error:\n' + msg + '\n' )

    def session_timeout(self, num_seconds=None):
        """
        This applies a timeout to the total time the remote session is alive.
        A positive value starts a session timer, while None will cancel it.
        If time expires while executing a function in this class, or has
        expired and a function of this class is called, a SessionTimeoutError
        is raised.
        """
        if num_seconds == None:
            tm = None
        else:
            tm = time.time() + num_seconds

        self._propogate_session_timeout( tm )

    def timeout(self, num_seconds):
        """
        Apply a timeout to the next command. For example,

            proxy.timeout(30).send( 'mylist = [1,2,3]' )
            proxy.timeout(30).myfunc( 42 )
            files = proxy.timeout(30).os.listdir('/path')
        """
        return TimeoutTemporary( num_seconds, self )

    def send(self, *code_or_objects):
        """
        Send raw python source code to the remote side, or the source code
        defining objects. Objects can be functions, class types, and/or
        modules. Module objects are made available on the remote side but
        must still be imported. For example,

            def afunc( arg ):
                return 2*arg
            proxy.send( afunc )
            rtn = proxy.afunc( 42 )
        """
        self._timeout_send( None, *code_or_objects )

    def construct(self, constructor, *args, **kwargs):
        """
        Create an object on the remote side and return a proxy object. These
        proxy objects are constrained to function calls only with arguments
        of implicit types, such as strings, numbers, lists, and dictionaries
        (anything for which "eval(repr(obj))" reproduces obj).
        """
        return self._timeout_construct( None, constructor, *args, **kwargs )

    def assign(self, name, constructor, *args, **kwargs):
        ""
        return self._timeout_assign( None, name, constructor, *args, **kwargs )

    def import_module(self, module_name):
        """
        Import a Python module on the remote side and return a proxy object.
        The module is also placed in the proxy namespace. For example,

            mod = proxy.import_module( 'os' )
            mod.chdir( 'subdir' )
            proxy.os.getpwd()

            mod = proxy.import_module( 'os.path' )
            mod.isfile( 'foobar.txt' )
            proxy.os.path.exists( 'foobar.txt' )

        Note that sys, os, and os.path are automatically imported.
        """
        return self._timeout_import_module( None, module_name )

    def shutdown(self):
        ""
        self.remote.close()

    ###################################################################

    def _initialize_builtins(self, timeout):
        ""
        err = send_internal_utilities( self.remote, timeout )

        if err:
            self.remote.close()

        else:
            obj1 = ObjectProxy( self.remote, 'os', self.endtime )
            obj2 = ObjectProxy( self.remote, 'os.path', self.endtime )
            obj3 = ObjectProxy( self.remote, 'sys', self.endtime )

            self.objs[ 'os' ] = obj1
            obj1.objs[ 'path' ] = obj2
            self.objs[ 'sys' ] = obj3

        return err

    def _timeout_send(self, timeout, *code_or_objects):
        ""
        for obj in code_or_objects:
            pycode = get_code_for_object_type( obj )
            send_object_code( self.remote, timeout, self.endtime, obj, pycode )

    def _timeout_construct( self, timeout, constructor, *args, **kwargs):
        ""
        self.objid += 1
        name = '_pythonproxy_object_'+str(self.objid)

        remote_function_call( self.remote, timeout, self.endtime,
            '_remotepython_construct_object', (name,constructor,)+args, kwargs )

        return ObjectProxy( self.remote, name, self.endtime )

    def _timeout_assign(self, timeout, name, constructor, *args, **kwargs):
        ""
        obj = self._timeout_construct( timeout, constructor, *args, **kwargs )
        self.objs[ name ] = obj
        return obj

    def _timeout_import_module(self, timeout, module_name ):
        ""
        names = []
        parent = self
        for name in module_name.strip().split('.'):

            names.append( name )
            modpath = '.'.join( names )

            obj = self._make_import_object( timeout, modpath )

            parent.objs[ name ] = obj
            parent = obj

        return obj

    def _make_import_object(self, timeout, modpath):
        ""
        if not self.remote.isAlive():
            raise FailedConnectionError( 'connection is not alive' )

        self.objid += 1
        objname = '_pythonproxy_object_'+str(self.objid)

        remote_function_call( self.remote, timeout, self.endtime,
            '_remotepython_import_module', (objname,modpath,), {} )

        return ObjectProxy( self.remote, objname, self.endtime )

    def _propogate_session_timeout(self, endtime):
        ""
        self.endtime = endtime
        for subobj in self.objs.values():
            subobj._propogate_session_timeout( endtime )

    def __getattr__(self, funcname):
        """
        This is called when an unknown class attribute is requested.  The
        implementation here returns a callable or an object proxy, which
        when called by the user code, will call into the remote python.
        """
        return _compute_object_attribute( self, funcname, None )

    def _get_object(self, funcname):
        ""
        return '', self.objs.get( funcname, None ), self.endtime


class python_proxy:
    """
    This is a context manager for a PythonProxy object.

        with python_proxy( 'sparky' ) as remote:
            remote.os.chdir( '/some/path' )
    """

    def __init__(self, machname,
                       startup_timeout=30,
                       pythonexe='python',
                       sshcmd='ssh',
                       bashlogin=False,
                       logfile=None ):
        ""
        self.proxy = PythonProxy( machname, pythonexe=pythonexe,
                                            sshcmd=sshcmd,
                                            bashlogin=bashlogin,
                                            logfile=logfile )
        self.proxy.start( startup_timeout )

    def __enter__(self):
        ""
        return self.proxy

    def __exit__(self, type, value, traceback):
        ""
        self.proxy.shutdown()


class ObjectProxy( object ):

    def __init__(self, remote, varname, endtime):
        ""
        self.remote = remote
        self.varname = varname
        self.endtime = endtime

        self.objs = {}

    def _propogate_session_timeout(self, endtime):
        ""
        self.endtime = endtime
        for subobj in self.objs.values():
            subobj._propogate_session_timeout( endtime )

    def __getattr__(self, funcname):
        ""
        return _compute_object_attribute( self, funcname, None )

    def _get_object(self, funcname):
        ""
        return self.varname, self.objs.get( funcname, None ), self.endtime


class TimeoutTemporary( object ):

    def __init__(self, timeout, target):
        ""
        self.timeout = timeout
        self.target = target

    def __getattr__(self, funcname):
        ""
        return _compute_object_attribute( self.target, funcname, self.timeout )


def _compute_object_attribute( target, funcname, timeout ):
    """
    returns a callable or a proxy object corresponding to 'funcname' relative
    to the given 'target' (which is a PythonProxy or an ObjectProxy)
    """
    # first look for a bound method starting with "_timeout_"
    # (which only occurs in the PythonProxy class)
    if not funcname.startswith('_'):
        try:
            meth = target.__getattribute__( '_timeout_'+funcname )
        except AttributeError:
            meth = None
        if meth:
            return lambda *args, **kwargs: meth( timeout, *args, **kwargs )

    # get the object variable name, and (if present) a sub-object for 'funcname'
    varname,obj,endtime = target._get_object( funcname )

    if obj != None:
        if timeout == None:
            # no reason to propogate the timeout
            return obj
        else:
            # propogate the timeout to the next object in the chain
            return TimeoutTemporary( timeout, obj )

    # compose the remote function name with the remote variable name
    if varname:
        fn = varname+'.'+funcname
    else:
        fn = funcname

    return lambda *args, **kwargs: remote_function_call( target.remote,
                                                         timeout,
                                                         endtime,
                                                         fn,
                                                         args,
                                                         kwargs )


_pythonproxy_return_marker    = '_pythonproxy_return='
_len_return_value_marker      = len( _pythonproxy_return_marker )
_pythonproxy_exception_marker = '_pythonproxy_exception='
_len_exception_marker         = len( _pythonproxy_exception_marker )


def remote_code_execution( remote, timeout, endtime, codelines ):
    ""
    if not remote.isAlive():
        raise FailedConnectionError( 'connection is not alive' )

    cmd = '_remotepython_try_except_code_lines('+repr(codelines)+')'
    remote.execute( cmd )
    wait_for_return_value( remote, timeout, endtime )


def remote_function_call( remote, timeout, endtime, funcname, args, kwargs ):
    ""
    if not remote.isAlive():
        raise FailedConnectionError( 'connection is not alive' )

    repr_args = [ repr(arg) for arg in args ]
    repr_kwargs = [ (k,repr(v)) for k,v in kwargs.items() ]

    cmd = '_remotepython_function_call(' + repr(funcname) + ',' + \
                                           repr(repr_args) + ',' + \
                                           repr(repr_kwargs) + ')'

    remote.execute( cmd )

    repr_rtn = wait_for_return_value( remote, timeout, endtime )

    try:
        rtn = eval( repr_rtn )
    except Exception:
        raise SerializationError( 'eval failed for return value: '+repr_rtn )

    return rtn


def wait_for_return_value( remote, timeout, endtime ):
    ""
    for out in remote_output_iterator( remote, timeout, endtime ):

        if out.startswith( _pythonproxy_return_marker ):
            val = out.strip()[_len_return_value_marker:]
            break

        elif out.startswith( _pythonproxy_exception_marker ):
            exc = eval( out.strip()[_len_exception_marker:] )
            fmtexc = format_remote_exception( exc )
            raise RemoteExceptionError( 'caught remote exception:\n'+fmtexc )

    return val


def remote_output_iterator( remote, timeout, endtime ):
    ""
    tstart = time.time()
    pause = 0.1

    while True:

        out = remote.getOutputLine()

        if out:
            yield out

        elif timeout != None and time.time() - tstart > timeout:
            secs = "%.1f" % (time.time()-tstart)
            raise CommandTimeoutError( 'timed out after '+secs+' seconds' )

        elif endtime != None and time.time() > endtime:
            raise SessionTimeoutError( 'session timed out at ' + \
                                       time.ctime(endtime) )

        elif not remote.isAlive():
            secs = "%.1f" % (time.time()-tstart)
            raise FailedConnectionError( 'connection lost after '+secs+' seconds' )

        else:
            time.sleep( pause )
            pause = min( pause * 2, 2 )


def send_object_code( remote, timeout, endtime, obj, pycode ):
    ""
    if type(obj) == types.ModuleType:
        cmd = '_remotepython_add_module('+repr(obj.__name__)+','+repr(pycode)+')'
        remote_code_execution( remote, timeout, endtime, cmd )
    else:
        remote_code_execution( remote, timeout, endtime, pycode )


def format_remote_exception( tbstring ):
    ""
    fmt = ''
    for line in tbstring.splitlines():
        fmt += 'remote: '+line+'\n'
    return fmt


def _pythonproxy_capture_traceback( excinfo ):
    ""
    xt,xv,xtb = excinfo
    xs = ''.join( traceback.format_exception_only( xt, xv ) )
    tb = 'Traceback (most recent call last):\n' + \
         ''.join( traceback.format_list(
                        traceback.extract_stack()[:-2] +
                        traceback.extract_tb( xtb ) ) ) + xs
    return tb


def _remotepython_try_except_code_lines( codelines ):
    ""
    try:
        filename = _remotepython_add_eval_linecache( codelines )
        eval( compile( codelines, filename, "exec" ), globals() )
        print ( _pythonproxy_return_marker+repr(None) )

    except Exception:
        tb = _pythonproxy_capture_traceback( sys.exc_info() )
        print ( _pythonproxy_exception_marker+repr(tb) )


def _remotepython_function_call( funcname, repr_args, repr_kwargs ):
    ""
    try:
        args = [ _pythonproxy_eval_argument(rep) for rep in repr_args ]

        kwargs = {}
        for k,repr_val in repr_kwargs:
            kwargs[k] = _pythonproxy_eval_argument( repr_val )

        rtn = eval( funcname+'(*args,**kwargs)' )
        print ( _pythonproxy_return_marker+repr(rtn) )

    except Exception:
        tb = _pythonproxy_capture_traceback( sys.exc_info() )
        print ( _pythonproxy_exception_marker+repr(tb) )


def _pythonproxy_eval_argument( repr_arg ):
    ""
    try:
        arg = eval( repr_arg )
    except Exception:
        raise SerializationError( 'eval failed for arg: '+repr_arg )

    return arg


def _remotepython_construct_object( varname, constructor, *args, **kwargs ):
    ""
    obj = eval( constructor + '( *args, **kwargs )' )
    globals()[ varname ] = obj


def _remotepython_import_module( varname, module_name ):
    ""
    eval( compile( 'import '+module_name, "<rpycmdr>", "exec" ) )
    globals()[ varname ] = eval( module_name )


_boot_code = """\
import sys
sys.dont_write_bytecode = True
sys.excepthook = sys.__excepthook__
import os
_pythonproxy_return_marker="""+repr(_pythonproxy_return_marker)+"""
_pythonproxy_exception_marker="""+repr(_pythonproxy_exception_marker)+"""
"""

def send_bootstrap_code( remote ):
    ""
    err = ''

    try:
        remote.execute( _boot_code )
        send_a_function( remote, _pythonproxy_capture_traceback )
        send_a_function( remote, _remotepython_try_except_code_lines )

    except Exception:
        err = _pythonproxy_capture_traceback( sys.exc_info() )

    return err


_UTILITIES_LIST = [
    _remotepython_function_call,
    _pythonproxy_eval_argument,
    _remotepython_construct_object,
    _remotepython_import_module,
    PythonProxyError,
    SerializationError,
]

def send_internal_utilities( remote, timeout, utils=_UTILITIES_LIST ):
    ""
    err = send_bootstrap_code( remote )

    if not err:
        try:
            for obj in utils:

                pycode = get_source_code( obj )
                if pycode == None:
                    err = 'Failed to get source code for '+str(obj)
                    break

                remote_code_execution( remote, timeout, None, pycode )

        except Exception:
            err = _pythonproxy_capture_traceback( sys.exc_info() )

    return err


def send_a_function( remote, func ):
    ""
    pycode = get_source_code( func )
    if pycode == None:
        raise Exception( 'Failed to get source code for '+str(func) )
    remote.execute( pycode )


def get_code_for_object_type( obj ):
    ""
    if type(obj) == type(''):
        pycode = obj

    else:
        pycode = get_source_code(obj)
        if pycode == None:
            raise PythonProxyError(
                        'could not find source code for '+str(obj) )

    return pycode


_cwd_at_import = os.getcwd()

def get_source_code( python_object, chdir=None ):
    """
    Gets and returns the python source code for the given function object or
    module.  If the source could not be retrieved, None is returned.  If 'chdir'
    is not None, the PWD is temporarily changed to help find the source code.
    """
    cwd = os.getcwd()

    dirs = [ chdir ]
    if chdir != None:
        dirs.append( None )
    dirs.append( _cwd_at_import )

    for cd in dirs:

        lines = None

        try:
            if cd:
                # sometimes the python object's source code file name is a
                # relative path, which creates a sensitivity to the current
                # working directory; change to the CWD at the time this file
                # was imported
                os.chdir( cd )

            lines,lineno = inspect.getsourcelines( python_object )

        except Exception:
            pass

        os.chdir( cwd )

        if lines != None:
            return ''.join( lines )

    return None
