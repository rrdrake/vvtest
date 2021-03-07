#!/usr/bin/env python

# Copyright 2018 National Technology & Engineering Solutions of Sandia, LLC
# (NTESS). Under the terms of Contract DE-NA0003525 with NTESS, the U.S.
# Government retains certain rights in this software.

import os, sys
import time
import signal
import subprocess

from .helpers import runcmd, format_extra_flags

class ProcessBatch:

    def __init__(self, ppn, **kwargs):
        ""
        self.ppn = max( ppn, 1 )
        self.dpn = max( int( kwargs.get( 'devices_per_node', 0 ) ), 0 )
        self.extra_flags = format_extra_flags(kwargs.get("extra_flags",None))

        self.childids = []

    def header(self, size, qtime, workdir, outfile, plat_attrs):
        """
        """
        np,ndevice = size

        hdr = '\n' + \
              '# np = '+str(np) + '\n' + \
              '# ndevice = '+str(ndevice) + '\n' + \
              '# qtime = '+str(qtime) + '\n' + \
              '# workdir = '+str(workdir) + '\n' + \
              '# outfile = '+str(outfile) + '\n\n' + \
              'cd '+workdir + ' || exit 1\n'

        return hdr

    def submit(self, fname, workdir, outfile,
                     queue=None, account=None, confirm=False, **kwargs):
        """
        Executes the script 'fname' as a background process.
        Returns (cmd, out, job id, error message) where 'cmd' is
        (approximately) the fork command and 'out' is a little informational
        message.  The job id is None if an error occured, and error
        message is a string containing the error.  If successful, job id is an
        integer.
        """
        sys.stdout.flush()
        sys.stderr.flush()

        jobid = os.fork()

        if jobid == 0:
            os.chdir(workdir)
            fpout = open( outfile, 'w' )
            os.dup2( fpout.fileno(), sys.stdout.fileno() )
            os.dup2( fpout.fileno(), sys.stderr.fileno() )
            sys.stdout.write( 'queue = '+str(queue) + '\n' + \
                              'account = '+str(account) + '\n\n' )
            sys.stdout.flush()
            os.execv( '/bin/csh', ['/bin/csh', '-f', fname] )

        cmd = '/bin/csh -f ' + fname + ' >& ' + outfile
        out = '[forked process '+str(jobid)+']'

        # keep the child process ids as the queue ids
        self.childids.append( jobid )

        return cmd, out, jobid, ''

    def query(self, jobidL):
        """
        Determine the state of the given job ids.  Returns (cmd, out, err, stateD)
        where stateD is dictionary mapping the job ids to a string equal to
        'pending', 'running', or '' (empty) and empty means either the job was
        not listed or it was listed but not pending or running.  The err value
        contains an error message if an error occurred when getting the states.
        """
        doneL = []
        jobD = {}
        for jobid in jobidL:
            if jobid in self.childids:
                cpid,xcode = os.waitpid( jobid, os.WNOHANG )
                if cpid > 0:
                    # child finished; empty string means done
                    jobD[jobid] = ''
                    doneL.append( jobid )
                else:
                    jobD[jobid] = 'running'
            else:
                jobD[jobid] = ''

        for jobid in doneL:
            self.childids.remove( jobid )

        out = ' '.join( [ str(jid) for jid in jobidL ] )
        return 'ps', out, '', jobD

    def cancel(self, jobid):
        ""
        print ( 'kill -s '+str(int(signal.SIGINT))+' '+str(jobid) )
        for pid in get_process_descendants( int(jobid) ):
            os.kill( pid, signal.SIGINT )


def get_process_descendants( parent ):
    ""
    lineL = get_process_list()

    pidset = set( [ parent ] )

    setlen = len( pidset )
    while True:
        for usr,pid,ppid in lineL:
            if ppid in pidset:
                pidset.add( pid )
        newlen = len( pidset )
        if newlen == setlen:
            break
        setlen = newlen

    return list( pidset )


def get_process_list():
    """
    Return a python list of all processes on the current machine, where each
    entry is a length three list of form

            [ user, pid, ppid ]
    """
    p = subprocess.Popen( 'ps -o user,pid,ppid -e',
                          shell=True, stdout=subprocess.PIPE )
    sout,serr = p.communicate()

    sout = _STRING_(sout).strip()+'\n'

    # strip off first non-empty line (the header)

    first = True
    lineL = []
    for line in sout.split( os.linesep ):
        line = line.strip()
        if line:
            if first:
                first = False
            else:
                L = line.split()
                if len(L) == 3:
                    try:
                        L[1] = int(L[1])
                        L[2] = int(L[2])
                    except Exception:
                        pass
                    else:
                        lineL.append( L )

    return lineL

if sys.version_info[0] < 3:
    def _STRING_(b): return b

else:
    bytes_type = type( ''.encode() )

    def _STRING_(b):
        if type(b) == bytes_type:
            return b.decode()
        return b


#########################################################################

if __name__ == "__main__":
    pass
