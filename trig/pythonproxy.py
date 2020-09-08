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

class RemoteExceptionError( PythonProxyError ):
    pass

class RemoteTimeoutError( PythonProxyError ):
    pass

class FailedConnectionError( PythonProxyError ):
    pass

class SerializationError( PythonProxyError ):
    pass


class RemotePythonProxy:
    """
    Uses the remotepython.RemotePython class to send python commands to a
    Python interpreter on a remote machine and return their output.

    To debug an interaction, provide a logfile to the constructor.  All
    messages to and from the remote python will be logged, including print
    statements being written by remote code.
    """

    def __init__(self, machine=None,
                       pythonexe='python',
                       sshcmd='ssh',
                       logfile=None ):
        ""
        self.timeout = None
        self.remote = RemotePython( machine, pythonexe, sshcmd, logfile )

        self.objid = 0
        self.objs = {}

    def start(self, timeout=30):
        """
        Establishes the connection, or raises FailedConnectionError on failure.
        """
        err = ''

        ok = self.remote.start( timeout )
        if ok:
            err = self._initialize_builtins( timeout )

        if not ok or err:
            msg = ( self.remote.getStartupOutput() + '\n' + err ).rstrip()
            raise FailedConnectionError( 'startup error:\n' + msg + '\n' )

    def set_timeout(self, timeout):
        ""
        if timeout == None or timeout < 0.001:
            self.timeout = None  # turn off timeout mechanism
        else:
            self.timeout = timeout

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
        for obj in code_or_objects:
            pycode = get_code_for_object_type( obj )
            send_object_code( self.remote, self.timeout, obj, pycode )

    def construct(self, constructor, *args, **kwargs):
        """
        Create an object on the remote side and return a proxy object. These
        proxy objects are constrained to function calls only with arguments
        of implicit types, such as strings, numbers, lists, and dictionaries
        (anything for which "eval(repr(obj))" reproduces obj).
        """
        self.objid += 1
        name = '_pythonproxy_object_'+str(self.objid)

        remote_function_call( self.remote, self.timeout,
            '_remotepython_construct_object', (name,constructor,)+args, kwargs )

        return ObjectProxy( self.remote, self.timeout, name )

    def assign(self, name, constructor, *args, **kwargs):
        ""
        obj = self.construct( constructor, *args, **kwargs )
        self.objs[ name ] = obj
        return obj

    def import_module(self, module_name):
        """
        Import a Python module on the remote side and return a proxy object.
        For example,

            remote_os = proxy.module( 'os' )
            remote_os.chdir( 'subdir' )
            remote_os.getpwd()

            remote_os_path = proxy.module( 'os.path' )
            remote_os_path.isfile( 'foobar.txt' )

        Note that sys, os, and os.path are automatically imported.
        """
        names = []
        parent = self
        for name in module_name.strip().split('.'):

            names.append( name )
            modpath = '.'.join( names )

            obj = self._make_import_object( modpath )

            parent.objs[ name ] = obj
            parent = obj

        return obj

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
            obj1 = ObjectProxy( self.remote, self.timeout, 'os' )
            obj2 = ObjectProxy( self.remote, self.timeout, 'os.path' )
            obj3 = ObjectProxy( self.remote, self.timeout, 'sys' )

            self.objs[ 'os' ] = obj1
            obj1.objs[ 'path' ] = obj2
            self.objs[ 'sys' ] = obj3

        return err

    def _make_import_object(self, modpath):
        ""
        if not self.remote.isAlive():
            raise FailedConnectionError( 'connection is not alive' )

        self.objid += 1
        objname = '_pythonproxy_object_'+str(self.objid)

        remote_function_call( self.remote, self.timeout,
            '_remotepython_import_module', (objname,modpath,), {} )

        return ObjectProxy( self.remote, self.timeout, objname )

    def __getattr__(self, funcname):
        """
        This is called when an unknown class attribute is requested.  The
        implementation here returns a function object that, when invoked,
        dispatches a call to 'funcname' on the remote side, waits for the
        remote return value, and returns that value on the local side.
        """
        if funcname in self.objs:
            return self.objs[funcname]
        return lambda *args, **kwargs: self._call_( funcname, args, kwargs )

    def _call_(self, funcname, args, kwargs):
        ""
        return remote_function_call( self.remote, self.timeout,
                                     funcname, args, kwargs )


class python_proxy:
    """
    This is a context manager for a RemotePythonProxy object.

        with python_proxy( 'sparky' ) as remote:
            remote.os.chdir( '/some/path' )
    """

    def __init__(self, machname,
                       startup_timeout=30,
                       pythonexe='python',
                       sshcmd='ssh',
                       logfile=None ):
        ""
        self.proxy = RemotePythonProxy( machname,
                                        pythonexe=pythonexe,
                                        sshcmd=sshcmd,
                                        logfile=logfile )
        self.proxy.start( startup_timeout )

    def __enter__(self):
        ""
        return self.proxy

    def __exit__(self, type, value, traceback):
        ""
        self.proxy.shutdown()


class ObjectProxy:

    def __init__(self, remote, timeout, name):
        ""
        self.remote = remote
        self.timeout = timeout
        self.name = name

        self.objs = {}

    def __getattr__(self, funcname):
        ""
        if funcname in self.objs:
            return self.objs[funcname]
        return lambda *args, **kwargs: self._call_( funcname, args, kwargs )

    def _call_(self, funcname, args, kwargs):
        ""
        return remote_function_call( self.remote, self.timeout,
                                     self.name+'.'+funcname, args, kwargs )


_pythonproxy_return_marker    = '_pythonproxy_return='
_len_return_value_marker      = len( _pythonproxy_return_marker )
_pythonproxy_exception_marker = '_pythonproxy_exception='
_len_exception_marker         = len( _pythonproxy_exception_marker )


def remote_code_execution( remote, timeout, codelines ):
    ""
    if not remote.isAlive():
        raise FailedConnectionError( 'connection is not alive' )

    cmd = '_remotepython_try_except_code_lines('+repr(codelines)+')'
    remote.execute( cmd )
    wait_for_return_value( remote, timeout )


def remote_function_call( remote, timeout, funcname, args, kwargs ):
    ""
    if not remote.isAlive():
        raise FailedConnectionError( 'connection is not alive' )

    repr_args = [ repr(arg) for arg in args ]
    repr_kwargs = [ (k,repr(v)) for k,v in kwargs.items() ]

    cmd = '_remotepython_function_call(' + repr(funcname) + ',' + \
                                           repr(repr_args) + ',' + \
                                           repr(repr_kwargs) + ')'

    remote.execute( cmd )

    repr_rtn = wait_for_return_value( remote, timeout )

    try:
        rtn = eval( repr_rtn )
    except Exception:
        raise SerializationError( 'eval failed for return value: '+repr_rtn )

    return rtn


def wait_for_return_value( remote, timeout ):
    ""
    for out in remote_output_iterator( remote, timeout ):

        if out.startswith( _pythonproxy_return_marker ):
            val = out.strip()[_len_return_value_marker:]
            break

        elif out.startswith( _pythonproxy_exception_marker ):
            exc = eval( out.strip()[_len_exception_marker:] )
            fmtexc = format_remote_exception( exc )
            raise RemoteExceptionError( 'caught remote exception:\n'+fmtexc )

    return val


def remote_output_iterator( remote, timeout ):
    ""
    tstart = time.time()
    pause = 0.1

    while True:

        out = remote.getOutputLine()

        if out:
            yield out

        elif timeout != None and time.time() - tstart > timeout:
            secs = "%.1f" % (time.time()-tstart)
            raise RemoteTimeoutError( 'timed out after '+secs+' seconds' )

        elif not remote.isAlive():
            secs = "%.1f" % (time.time()-tstart)
            raise FailedConnectionError( 'connection lost after '+secs+' seconds' )

        else:
            time.sleep( pause )
            pause = min( pause * 2, 2 )


def send_object_code( remote, timeout, obj, pycode ):
    ""
    if type(obj) == types.ModuleType:
        cmd = '_remotepython_add_module('+repr(obj.__name__)+','+repr(pycode)+')'
        remote_code_execution( remote, timeout, cmd )
    else:
        remote_code_execution( remote, timeout, pycode )


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

                remote_code_execution( remote, timeout, pycode )

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
