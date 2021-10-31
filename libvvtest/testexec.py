#!/usr/bin/env python

# Copyright 2018 National Technology & Engineering Solutions of Sandia, LLC
# (NTESS). Under the terms of Contract DE-NA0003525 with NTESS, the U.S.
# Government retains certain rights in this software.

import os, sys
import subprocess
import signal
import time
import traceback
import platform

not_windows = not platform.uname()[0].lower().startswith('win')

# if a test times out, it receives a SIGINT.  if it doesn't finish up
# after that in this number of seconds, it gets sent a SIGKILL
interrupt_to_kill_timeout = 30


class TestExec:
    """
    Runs a test in the background and provides methods to poll and kill it.
    """
    
    def __init__(self, tcase):
        ""
        self.tcase = tcase

        self.timeout = 0
        self.rundir = None
        self.resource_obj = None

        self.pid = None
        self.tstart = None
        self.tstop = None

        self.timedout = None     # time.time() if the test times out
        self.exit_status = None  # subprocess exit status or None if timed out

    def getTestCase(self):
        ""
        return self.tcase

    def setRunDirectory(self, rundir):
        ""
        self.rundir = rundir

    def getRunDirectory(self):
        ""
        return self.rundir

    def setTimeout(self, value):
        ""
        self.timeout = value

    def getTimeout(self):
        ""
        return self.timeout

    def setResourceObject(self, obj):
        ""
        self.resource_obj = obj

    def getResourceObject(self):
        ""
        return self.resource_obj

    def start(self, execute_test_func, rtconfig, is_baseline, perms,
                    fork_supported=True):
        """
        Launches the child process.
        """
        assert self.pid == None

        self.tstart = time.time()

        sys.stdout.flush()
        sys.stderr.flush()
        logfp = self._open_logfile( rtconfig, is_baseline, perms )

        cwd = os.getcwd()
        try:
            os.chdir( self.rundir )

            if fork_supported:
                self.pid = self.prepare_then_execute(
                                    execute_test_func, is_baseline, logfp )
            else:
                self.subpid = self.forkless_prepare_then_execute(
                                    execute_test_func, is_baseline, logfp )
        finally:
            self._close_logfile( logfp )
            os.chdir( cwd )

    def _open_logfile(self, rtconfig, is_baseline, perms):
        ""
        logfile = None
        if rtconfig.getAttr('logfile'):
            logfile = self.tcase.getSpec().getLogFilename( is_baseline )

        if logfile:
            if not os.path.isabs( logfile ):
                logfile = os.path.join( self.rundir, logfile )
            logfp = open( logfile, 'w+' )

            perms.apply( logfile )
        else:
            logfp = None

        return logfp

    def _close_logfile(self, logfp):
        ""
        if logfp:
            logfp.close()

    def getStartTime(self):
        ""
        return self.tstart

    def isStarted(self):
        ""
        return self.tstart is not None

    def poll(self):
        """
        returns True only if the test just finished
        """
        transition = False

        if self.isStarted() and not self.isDone():

            if self.pid:

                assert self.pid > 0

                cpid,code = os.waitpid( self.pid, os.WNOHANG )

                if cpid > 0:

                    # test finished

                    self.tstop = time.time()

                    if self.timedout is None:
                        self.exit_status = decode_subprocess_exit_code( code )

                    transition = True

                elif self.timeout > 0:
                    # not done .. check for timeout
                    tm = time.time()
                    if tm-self.tstart > self.timeout:
                        if self.timedout is None:
                            # interrupt all processes in the process group
                            self.signalJob( signal.SIGINT )
                            self.timedout = tm
                        elif (tm - self.timedout) > interrupt_to_kill_timeout:
                            # SIGINT isn't killing fast enough, use stronger method
                            self.signalJob( signal.SIGTERM )

            else:
                if self.subpid is None:
                    # test finished during startup
                    assert self.exit_status is not None
                    self.tstop = time.time()
                    transition = True

                else:
                    code = self.subpid.poll()
                    if code is not None:
                        self.tstop = time.time()
                        self.exit_status = code
                        transition = True
                    elif self.timeout > 0:
                        tm = time.time()
                        if tm-self.tstart > self.timeout:
                            self.tstop = tm
                            self.timedout = tm
                            self.subpid.terminate()
                            transition = True

        return transition

    def isDone(self):
        ""
        return self.tstop is not None

    def getExitInfo(self):
        ""
        return self.exit_status, self.timedout

    def signalJob(self, sig):
        """
        Sends a signal to the job, such as signal.SIGINT.
        """
        try:
            if self.pid is not None:
                os.kill( self.pid, sig )
            elif self.subpid is not None:
                self.subpid.terminate()
        except Exception:
            pass

    def killJob(self):
        """
        Sends the job a SIGINT signal, waits a little, and if the job
        has not shutdown, sends it SIGTERM followed by SIGKILL.
        """
        self.signalJob( signal.SIGINT )
        time.sleep(2)

        t1 = self.poll()

        t2 = False
        if not self.isDone():
            self.signalJob( signal.SIGTERM )
            time.sleep(5)
            t2 = self.poll()
        
        return t1 or t2

    def prepare_then_execute(self, execute_test_func, is_baseline, logfp):
        ""
        pid = os_fork_with_retry( 10 )
        if pid == 0:
            # this is the new child process

            redirect_stdout_err( logfp )

            try:
                cmd_list = execute_test_func( self, is_baseline )

                sys.stdout.flush() ; sys.stderr.flush()

                if cmd_list == None:
                    # can only happen in baseline mode
                    os._exit(0)
                else:
                    x = group_exec_subprocess( cmd_list )
                    os._exit(x)

            except:
                sys.stdout.flush() ; sys.stderr.flush()
                traceback.print_exc()
                sys.stdout.flush() ; sys.stderr.flush()
                os._exit(1)

        return pid

    def forkless_prepare_then_execute(self, execute_test_func, is_baseline, logfp):
        ""
        subpid = None
        with redirect_output( logfp ):
            try:
                cmd_list = execute_test_func( self, is_baseline )
                if cmd_list is None:
                    # can only happen in baseline mode
                    self.exit_status = 0
                elif logfp is None:
                    subpid = subprocess.Popen( cmd_list )
                else:
                    subpid = subprocess.Popen( cmd_list,
                                               stdout=logfp.fileno(),
                                               stderr=subprocess.STDOUT )
            except Exception:
                sys.stdout.flush() ; sys.stderr.flush()
                traceback.print_exc()

                self.exit_status = 1

        return subpid


class redirect_output:
    """
    with redirect_output( fileobj ):
        do_something()
    """

    def __init__(self, fileptr):
        ""
        self.fp = fileptr

    def __enter__(self):
        ""
        if self.fp is not None:
            self.save_stdout_fd = os.dup(1)
            os.dup2( self.fp.fileno(), 1 )

            self.save_stderr_fd = os.dup(2)
            os.dup2( self.fp.fileno(), 2 )

    def __exit__(self, type, value, traceback):
        ""
        sys.stdout.flush()
        sys.stderr.flush()

        if self.fp is not None:
            os.dup2( self.save_stdout_fd, 1 )
            os.close( self.save_stdout_fd )

            os.dup2( self.save_stderr_fd, 2 )
            os.close( self.save_stderr_fd )


def redirect_stdout_err( logfp ):
    ""
    if logfp:
        # reassign stdout & stderr file descriptors to the log file
        os.dup2( logfp.fileno(), sys.stdout.fileno() )
        os.dup2( logfp.fileno(), sys.stderr.fileno() )


def decode_subprocess_exit_code( exit_code ):
    ""
    if os.WIFEXITED( exit_code ):
        return os.WEXITSTATUS( exit_code )

    if os.WIFSIGNALED( exit_code ) or os.WIFSTOPPED( exit_code ):
        return 1

    if exit_code == 0:
        return 0

    return 1


def os_fork_with_retry( numtries ):
    ""
    assert numtries > 0

    pause = 0.5

    for i in range(numtries):

        try:
            pid = os.fork()
            break

        except OSError:
            # the BlockingIOError subclass of OSError has been seen on heavily
            # loaded machines; given some time between retries, it will often
            # succeed
            if i+1 == numtries:
                raise
            time.sleep( pause )
            pause *= 2

    return pid


def group_exec_subprocess( cmd, **kwargs ):
    """
    Run the given command in a subprocess in its own process group, then wait
    for it.  Catch all signals and dispatch them to the child process group.

    The SIGTERM and SIGHUP signals are sent to the child group, but they also
    cause a SIGKILL to be sent after a short delay.

    This function modifies the current environment by registering signal
    handlers, so the intended use is something like this

        pid = os.fork()
        if pid == 0:
            x = group_exec_subprocess( 'some command', shell=True )
            os._exit(x)
    """
    register_signal_handlers()

    terminate_delay = kwargs.pop( 'terminate_delay', 5 )

    kwargs[ 'preexec_fn' ] = lambda: os.setpgid( os.getpid(), os.getpid() )
    proc = subprocess.Popen( cmd, **kwargs )

    while True:
        try:
            x = proc.wait()
            break
        except KeyboardInterrupt:
            os.kill( -proc.pid, signal.SIGINT )
        except SignalException:
            e = sys.exc_info()[1]
            os.kill( -proc.pid, e.sig )
            if e.sig in [ signal.SIGTERM, signal.SIGHUP ]:
                x = check_terminate_subprocess( proc, terminate_delay )
                break
        except:
            os.kill( -proc.pid, signal.SIGTERM )

    return x


class SignalException( Exception ):
    def __init__(self, signum):
        self.sig = signum
        Exception.__init__( self, 'Received signal '+str(signum) )

def signal_handler( signum, frame ):
    raise SignalException( signum )


def register_signal_handlers( reset=False ):
    ""
    if reset:
        handler = signal.SIG_DFL
    else:
        handler = signal_handler

    signal.signal( signal.SIGTERM, handler )
    signal.signal( signal.SIGABRT, handler )
    signal.signal( signal.SIGHUP, handler )
    signal.signal( signal.SIGALRM, handler )
    signal.signal( signal.SIGUSR1, handler )
    signal.signal( signal.SIGUSR2, handler )


def check_terminate_subprocess( proc, terminate_delay ):
    ""
    if terminate_delay:
        time.sleep( terminate_delay )

    x = proc.poll()

    os.kill( -proc.pid, signal.SIGKILL )

    return x
