#!/usr/bin/env python

# Copyright 2018 National Technology & Engineering Solutions of Sandia, LLC
# (NTESS). Under the terms of Contract DE-NA0003525 with NTESS, the U.S.
# Government retains certain rights in this software.

import os, sys
import time
import signal
import subprocess


class SubProcs:

    def __init__(self, **attrs):
        ""
        self.attrs = attrs
        self.kids = {}  # pid -> Popen object

    def header(self, size, qtime, outfile):
        ""
        return [ '# size = '+repr(size),
                 '# qtime = '+repr(qtime),
                 '# outfile = '+repr(outfile) ]

    def submit(self, fname, outfile):
        """
        Submit 'fname' to the batch system. Should return
            ( jobid, submit command, raw output from submit command )
        where jobid is None if an error occurred.
        """
        cmd = '/bin/bash ' + fname + ' >& ' + outfile

        with open( outfile, 'wt' ) as fp:
            child = subprocess.Popen( ['/bin/bash', fname],
                                      stdout=fp.fileno(),
                                      stderr=subprocess.STDOUT )

        # use the child processes as the queue ids
        jobid = child.pid
        self.kids[jobid] = child

        out = '[subprocess '+str(jobid)+']'

        return jobid,cmd,out

    def query(self, jobids):
        """
        Determine the state of the given job ids.  Should return
            ( status dictionary, query command, raw output )
        where the status dictionary maps
            job id -> "running" or "pending" (waiting to run)
        Exclude job ids that are not running or pending.
        """
        jobD = {}
        out = ''
        for jobid,child in list( self.kids.items() ):
            if child.poll() is None:
                out += str(jobid)+' running\n'
                if jobid in jobids:
                    jobD[jobid] = 'running'
            else:
                out += str(jobid)+' done\n'
                self.kids.pop( jobid )  # child is done

        return jobD,'ps',out

    def cancel(self, jobid):
        ""
        print ( 'kill -s '+str(int(signal.SIGINT))+' '+str(jobid) )
        for pid in get_process_descendants( jobid ):
            os.kill( pid, signal.SIGINT )
        if jobid in self.kids:
            child = self.kids.pop( jobid )
            child.wait()


def get_process_descendants( parent ):
    ""
    lineL = get_process_list()

    pidset = set( [ int(parent) ] )

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

    if sys.version_info[0] < 3:
        sout = sout if sout else ''
    else:
        sout = sout.decode() if sout else ''

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
