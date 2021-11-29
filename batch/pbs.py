#!/usr/bin/env python

# Copyright 2018 National Technology & Engineering Solutions of Sandia, LLC
# (NTESS). Under the terms of Contract DE-NA0003525 with NTESS, the U.S.
# Government retains certain rights in this software.

import os, sys
import time
import shlex

from .helpers import runcmd, format_extra_flags

class BatchPBS:

    def __init__(self, ppn, **attrs):
        """
        The 'variation' attribute causes the header to be created a little
        differently.  The only known value is:

          "select" : The -lselect= option is used instead of -lnodes= such as
                       -l select=<num nodes>:mpiprocs=<ppn>:ncpus=<ppn>
                     where <num nodes> is the number of nodes needed and <ppn>
                     is the number of processors per node.

        By default, the -lnodes method is used.
        """
        self.attrs = attrs
        self.ppn = max( ppn, 1 )
        self.variation = attrs.get( 'variation', None )
        self.extra_flags = format_extra_flags(attrs.get("extra_flags",None))

        self.runcmd = runcmd

    def setRunCommand(self, run_function):
        ""
        self.runcmd = run_function

    def header(self, size, qtime, outfile):
        ""
        np,ndevice = size

        if np <= 0: np = 1
        nnodes = int( np/self.ppn )
        if (np%self.ppn) != 0:
            nnodes += 1

        if self.variation != None and self.variation == "select":
            hdr = '#PBS -l select=' + str(nnodes) + \
                   ':mpiprocs=' + str(self.ppn) + ':ncpus='+str(self.ppn)+'\n'
        else:
            hdr = '#PBS -l nodes=' + str(nnodes) + ':ppn=' + str(self.ppn)+'\n'

        hdr = hdr +  '#PBS -l walltime=' + self.HMSformat(qtime) + '\n' + \
                     '#PBS -j oe\n' + \
                     '#PBS -o ' + outfile + '\n'

        return hdr


    def submit(self, fname, outfile):
        """
        Creates and executes a command to submit the given filename as a batch
        job to the resource manager.  Returns (cmd, out, job id, error message)
        where 'cmd' is the submit command executed, 'out' is the output from
        running the command.  The job id is None if an error occured, and error
        message is a string containing the error.  If successful, job id is an
        integer.
        """
        queue = self.attrs.get( 'queue', None )
        account = self.attrs.get( 'account', None )

        cmdL = ['qsub']+self.extra_flags
        if queue != None: cmdL.extend(['-q',queue])
        if account != None: cmdL.extend(['-A',account])
        cmdL.extend(['-o', outfile])
        cmdL.extend(['-j', 'oe'])
        cmdL.append(fname)
        cmd = ' '.join( cmdL )

        x, out = self.runcmd( cmdL )

        # output should contain something like the following
        #    12345.ladmin1
        jobid = None
        s = out.strip()
        if s:
            L = s.split()
            if len(L) == 1:
                jobid = s

        if jobid == None:
            return cmd, out, None, "batch submission failed or could not parse " + \
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
        cmdL = ['qstat']
        cmd = ' '.join( cmdL )
        x, out = self.runcmd(cmdL)

        # create a dictionary with the results; maps job id to a status string
        stateD = {}
        for j in jobidL:
            stateD[j] = ''  # default to done

        err = ''
        for line in out.strip().split( os.linesep ):
            try:
                L = line.split()
                if len(L) == 6:
                    jid = L[0]
                    st = L[4]
                    # the output from qstat may return a truncated job id,
                    # so match the beginning of the incoming 'jobidL' strings
                    for j in jobidL:
                        if j.startswith( jid ):
                            if st in ['R']: st = 'running'
                            elif st in ['Q']: st = 'pending'
                            else: st = ''
                            stateD[j] = st
                            break
            except Exception:
                e = sys.exc_info()[1]
                err = "failed to parse squeue output: " + str(e)

        return cmd, out, err, stateD


    def HMSformat(self, nseconds):
        """
        Formats 'nseconds' in H:MM:SS format.  If the argument is a string, then
        it checks for a colon.  If it has a colon, the string is untouched.
        Otherwise it assumes seconds and converts to an integer before changing
        to H:MM:SS format.
        """
        if type(nseconds) == type(''):
            if ':' in nseconds:
                return nseconds
        nseconds = int(nseconds)
        nhrs = int( float(nseconds)/3600.0 )
        t = nseconds - nhrs*3600
        nmin = int( float(t)/60.0 )
        nsec = t - nmin*60
        if nsec < 10: nsec = '0' + str(nsec)
        else:         nsec = str(nsec)
        if nhrs == 0:
            return str(nmin) + ':' + nsec
        else:
            if nmin < 10: nmin = '0' + str(nmin)
            else:         nmin = str(nmin)
        return str(nhrs) + ':' + nmin + ':' + nsec
