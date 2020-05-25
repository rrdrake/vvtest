
import sys, os
import inspect
import traceback
import time

from remotepython import RemotePython


class PythonProxyError( Exception ):
    pass

class RemoteExceptionError( PythonProxyError ):
    pass

class RemoteTimeoutError( PythonProxyError ):
    pass

class FailedConnectionError( PythonProxyError ):
    pass


class RemotePythonProxy:
    """
    Uses the remotepython.RemotePython class to send python commands to a
    Python interpreter on a remote machine and return their output.

    To debug an interaction, provide a logfile.  All messages to and from
    the remote python will be logged, including any print statements being
    written by remote code.
    """

    def __init__(self, machine=None,
                       remotepython='python',
                       sshexe='ssh',
                       logfile=None ):
        ""
        self.timeout = None
        self.remote = RemotePython( machine, remotepython, sshexe, logfile )

    def start(self, timeout=30):
        """
        Establishes the connection, or raises FailedConnectionError on failure.
        """
        err = ''

        ok = self.remote.start( timeout )
        if ok:
            err = _send_internal_utilities( self.remote )

        if not ok or err:
            msg = ( self.remote.getStartupOutput() + '\n' + err ).rstrip()
            raise FailedConnectionError( 'startup error:\n' + msg + '\n' )

    def setRemoteTimeout(self, timeout):
        ""
        if timeout == None or timeout < 0.001:
            self.timeout = None
        else:
            self.timeout = timeout

    def execute(self, *lines_of_python_code):
        """
        Lines of python code can be sent as strings with newlines and/or
        separate arguments.
        """
        if not self.remote.isAlive():
            raise FailedConnectionError( 'connection is not alive' )

        self.remote.execute( *lines_of_python_code )

    def send(self, *objects):
        """
        The source code for Python modules, classes, and functions can be
        sent to the remote by specifying objects.  For example,

            def afunc( arg ):
                print ( arg )
            proxy.send( afunc )
        """
        for obj in objects:
            pycode = get_source_code(obj)
            assert pycode != None, 'could not find source code for '+str(obj)
            self.execute( pycode )

    def call(self, funcname, *args, **kwargs):
        ""
        # magic: add pythonproxy_timeout to kwargs
        rtn = remote_function_call( self.remote, self.timeout,
                                    funcname, args, kwargs )
        return rtn

    def construct(self, constructor, *args, **kwargs):
        """
        Create an object on the remote side and return a proxy object. These
        proxy objects are constrained to function calls only with arguments
        of implicit types, such as strings, numbers, lists, and dictionaries
        (anything for which "eval(repr(obj))" reproduces obj).
        """
        if not self.remote.isAlive():
            raise FailedConnectionError( 'connection is not alive' )

        obj = ObjectProxy( self.remote, self.timeout,
                           constructor, args, kwargs )
        return obj

    def module(self, module_name):
        """
        Import a Python module on the remote side and return a proxy object.
        For example,

            remote_os = proxy.module( 'os' )
            remote_os.chdir( 'subdir' )
            remote_os.getpwd()

            remote_os_path = proxy.module( 'os.path' )
            remote_os_path.isfile( 'foobar.txt' )
        """
        if not self.remote.isAlive():
            raise FailedConnectionError( 'connection is not alive' )

        obj = ObjectProxy( self.remote, self.timeout,
                           '_pythonproxy_import_module', (module_name,), {} )
        return obj

    def close(self):
        ""
        self.remote.close()


class python_proxy:
    """
    with python_proxy( 'sparky' ) as proxy:
        pass
    """

    def __init__(self, machname,
                       startup_timeout=30,
                       remotepython='python',
                       sshexe='ssh',
                       logfile=None ):
        ""
        self.proxy = RemotePythonProxy( machname,
                                        remotepython=remotepython,
                                        sshexe=sshexe,
                                        logfile=logfile )
        self.proxy.start( startup_timeout )

    def __enter__(self):
        ""
        return self.proxy

    def __exit__(self, type, value, traceback):
        ""
        self.proxy.close()


class ObjectProxy:

    def __init__(self, pycmds, timeout, constructor, args, kwargs):
        ""
        self.remote = pycmds
        self.timeout = timeout

        rtn = remote_function_call( self.remote, self.timeout,
                '_pythonproxy_construct_object', (constructor,)+args, kwargs )

        self.objid = repr( rtn )

    def setRemoteTimeout(self, timeout):
        ""
        if timeout == None or timeout < 0.001:
            self.timeout = None
        else:
            self.timeout = timeout

    def __getattr__(self, funcname):
        """
        This is called when an unknown class attribute is requested.  The
        implementation here returns a function object that, when invoked,
        dispatches a call to 'funcname' on the remote side, waits for the
        remote return value, and returns that value on the local side.
        """
        return lambda *args, **kwargs: self._call_( funcname, args, kwargs )

    def _call_(self, funcname, args, kwargs):
        ""
        func = '_pythonproxy_object_store['+self.objid+'].' + funcname
        return remote_function_call( self.remote, self.timeout, func, args, kwargs )


_return_value_marker     = '_pythonproxy_return_value='
_len_return_value_marker = len( _return_value_marker )
_exception_marker        = '_pythonproxy_exception='
_len_exception_marker    = len( _exception_marker )


def remote_function_call( remote, timeout, funcname, args, kwargs ):
    ""
    cmd = compose_remote_command( funcname, args, kwargs )

    if not remote.isAlive():
        raise FailedConnectionError( 'connection is not alive' )

    remote.execute(
        'try:',
        '  '+cmd,
        'except Exception:',
        '  tb = _pythonproxy_capture_traceback( sys.exc_info() )',
        '  print ( "'+_exception_marker+'"+repr(tb) )' )

    val = wait_for_return_value( remote, timeout )

    return eval( val )


def compose_remote_command( funcname, args, kwargs ):
    ""
    sig = []

    for arg in args:
        sig.append( repr(arg) )

    for k,v in kwargs.items():
        sig.append( k+'='+repr(v) )

    call = funcname+'('+','.join(sig)+')'
    cmd = 'print ( "'+_return_value_marker+'"+repr('+call+') )'

    return cmd


def wait_for_return_value( remote, timeout ):
    ""
    tstart = time.time()
    pause = 0.1

    while True:

        out = remote.getOutputLine()

        if out:
            if out.startswith( _return_value_marker ):
                val = out.strip()[_len_return_value_marker:]
                break
            elif out.startswith( _exception_marker ):
                exc = eval( out.strip()[_len_exception_marker:] )
                fmtexc = _format_remote_exception( exc )
                raise RemoteExceptionError( 'caught remote exception:\n'+fmtexc )

        elif timeout != None and time.time() - tstart > timeout:
            secs = "%.1f" % (time.time()-tstart)
            raise RemoteTimeoutError( 'timed out after '+secs+' seconds' )

        elif not remote.isAlive():
            secs = "%.1f" % (time.time()-tstart)
            raise FailedConnectionError( 'connection lost after '+secs+' seconds' )

        else:
            time.sleep( pause )
            pause = min( pause * 2, 2 )

    return val


def _pythonproxy_construct_object( constructor_funcname, *args, **kwargs ):
    """
    uses the global variable '_pythonproxy_object_store' to map ids to objects
    """
    obj = eval( constructor_funcname + '( *args, **kwargs )' )
    objid = id( obj )
    _pythonproxy_object_store[ objid ] = obj
    return objid


def _pythonproxy_import_module( module_name ):
    ""
    eval( compile( 'import '+module_name, "<rpycmdr>", "exec" ) )
    obj = eval( module_name )
    return obj


def _pythonproxy_capture_traceback( excinfo ):
    ""
    xt,xv,xtb = excinfo
    xs = ''.join( traceback.format_exception_only( xt, xv ) )
    tb = 'Traceback (most recent call last):\n' + \
         ''.join( traceback.format_list(
                        traceback.extract_stack()[:-2] +
                        traceback.extract_tb( xtb ) ) ) + xs
    return tb


_UTILITIES_LIST = [ 'import sys',
                    'sys.dont_write_bytecode = True',
                    'sys.excepthook = sys.__excepthook__',
                    'import os',
                    '_pythonproxy_object_store = {}',
                    _pythonproxy_construct_object,
                    _pythonproxy_import_module,
                    _pythonproxy_capture_traceback ]

def _send_internal_utilities( remote, utils=_UTILITIES_LIST ):
    ""
    err = ''

    try:
        for util in utils:
            if type(util) == type(''):
                pycode = util
            else:
                pycode = get_source_code( util )
                if pycode == None:
                    err = 'Failed to get source code for '+str(util)
                    break
            remote.execute( pycode )

    except Exception:
        err = _pythonproxy_capture_traceback( sys.exc_info() )

    if err:
        remote.close()

    return err


def _format_remote_exception( tbstring ):
    ""
    fmt = ''
    for line in tbstring.splitlines():
        fmt += 'remote: '+line+'\n'
    return fmt


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
