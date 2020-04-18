#!/usr/bin/env python

# Copyright 2018 National Technology & Engineering Solutions of Sandia, LLC
# (NTESS). Under the terms of Contract DE-NA0003525 with NTESS, the U.S.
# Government retains certain rights in this software.

import os, sys
from os.path import basename
import time
import re

from .helpers import runcmd

jobpat = re.compile( r'Job\s+<\d+>\s+is submitted to' ) #, re.MULTILINE )

class BatchLSF:

    def __init__(self, ppn, **kwargs):
        ""
        if ppn <= 0: ppn = 1
        self.ppn = ppn
        self.dpn = max( int( kwargs.get( 'devices_per_node', 0 ) ), 0 )
        self.runcmd = runcmd

    def setRunCommand(self, run_function):
        ""
        self.runcmd = run_function

    def header(self, size, qtime, workdir, outfile, plat_attrs):
        ""
        nnodes = self.computeNumNodes( size )

        hdr = '#BSUB -W ' + minutes_of_time(qtime) + '\n' + \
              '#BSUB -nnodes ' + str(nnodes) + '\n' + \
              '#BSUB -o ' + outfile + '\n' + \
              '#BSUB -e ' + outfile + '\n' + \
              'cd ' + workdir + ' || exit 1\n'

        return hdr

    def computeNumNodes(self, size):
        ""
        np,ndevice = size

        nnode1 = self._num_nodes( np, self.ppn )

        if self.dpn > 0 and ndevice != None:
            nnode2 = self._num_nodes( ndevice, self.dpn )
        else:
            nnode2 = 0

        return max( nnode1, nnode2 )

    def _num_nodes(self, num, numper):
        ""
        num = max( 0, num )
        if num > 0:
            nnode = int( num/numper )
            if (num%numper) != 0:
                nnode += 1
        else:
            nnode = 0

        return nnode

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
