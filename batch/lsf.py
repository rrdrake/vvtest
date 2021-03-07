#!/usr/bin/env python

# Copyright 2018 National Technology & Engineering Solutions of Sandia, LLC
# (NTESS). Under the terms of Contract DE-NA0003525 with NTESS, the U.S.
# Government retains certain rights in this software.

import os, sys
from os.path import basename
import time
import re

from .helpers import runcmd, compute_num_nodes, format_extra_flags


jobpat = re.compile( r'Job\s+<\d+>\s+is submitted to' ) #, re.MULTILINE )

class BatchLSF:

    def __init__(self, ppn, **kwargs):
        ""
        self.ppn = max( 1, ppn )
        self.dpn = max( int( kwargs.get( 'devices_per_node', 0 ) ), 0 )
        self.runcmd = runcmd
        self.extra_flags = format_extra_flags(kwargs.get("extra_flags"))

    def setRunCommand(self, run_function):
        ""
        self.runcmd = run_function

    def header(self, size, qtime, workdir, outfile, plat_attrs):
        ""
        nnodes = compute_num_nodes( size, self.ppn, self.dpn )

        hdr = '#BSUB -W ' + minutes_of_time(qtime) + '\n' + \
              '#BSUB -nnodes ' + str(nnodes) + '\n' + \
              '#BSUB -o ' + outfile + '\n' + \
              '#BSUB -e ' + outfile + '\n' + \
              'cd ' + workdir + ' || exit 1\n'

        return hdr

    def submit(self, fname, workdir, outfile,
                     queue=None, account=None, **kwargs):
        """
        Creates and executes a command to submit the given filename as a batch
        job to the resource manager.  Returns (cmd, out, job id, error message)
        where 'cmd' is the submit command executed, 'out' is the output from
        running the command.  The job id is None if an error occured, and error
        message is a string containing the error.  If successful, job id is an
        integer.
        """
        cmdL = ['bsub']
        if self.extra_flags is not None:
            cmdL.extend(self.extra_flags)
        cmdL.extend( [ '-J', basename(fname) ] )
        cmdL.extend( [ '-e', outfile ] )
        cmdL.extend( [ '-o', outfile ] )
        cmdL.extend( [ '-cwd', workdir ] )

        if queue != None:
            cmdL.extend( [ '-q', queue ] )

        if account != None:
            pass

        cmdL.append(fname)
        cmd = ' '.join( cmdL )

        x, out = self.runcmd( cmdL, workdir )

        # output should contain something like
        #    Job <68628> is submitted to default queue <normal>.
        jobid = None
        mat = jobpat.search( out )
        if mat != None:
            mL = mat.group().split()
            if len(mL) > 2:
                try:
                    jobid = int( mL[1].strip('<').strip('>') )
                except Exception:
                    jobid = None

        if jobid == None:
            return cmd, out, None, \
                    "batch submission failed or could not parse " + \
                    "output to obtain the job id"

        return cmd, out, jobid, ""

    def query(self, jobidL):
        """
        Determine the state of the given job ids.  Returns (cmd, out, err, stateD)
        where stateD is dictionary mapping the job ids to a string equal to
        'pending', 'running', or '' (empty) and empty means either the job was
        not listed or it was listed but not pending or running.  The err value
        contains an error message if an error occurred when getting the states.
        """
        cmdL = ['bjobs', '-noheader', '-o', 'jobid stat']
        cmd = ' '.join( cmdL )
        x, out = self.runcmd(cmdL)

        stateD = {}
        for jid in jobidL:
            stateD[jid] = ''  # default to done

        err = ''
        for line in out.splitlines():
            try:
                L = line.split()
                if len(L) == 2:
                    try:
                        jid = int(L[0])
                        st = L[1]
                    except Exception:
                        pass
                    else:
                        if jid in stateD:
                            if st in ['PROV','RUN','USUSP']: st = 'running'
                            elif st in ['PEND','PSUSP','WAIT']: st = 'pending'
                            else: st = ''
                            stateD[jid] = st
            except Exception:
                e = sys.exc_info()[1]
                err = "failed to parse squeue output: " + str(e)

        return cmd, out, err, stateD

    def cancel(self, jobid):
        ""
        print ( 'bkill '+str(jobid) )
        x, out = self.runcmd( [ 'bkill', str(jobid) ] )


def minutes_of_time( seconds ):
    ""
    return str( max( 1, int( float(seconds)/60. + 0.5 ) ) )
