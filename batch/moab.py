#!/usr/bin/env python

# Copyright 2018 National Technology & Engineering Solutions of Sandia, LLC
# (NTESS). Under the terms of Contract DE-NA0003525 with NTESS, the U.S.
# Government retains certain rights in this software.

import os, sys
import time

"""
This batch handler was written for Trinity, but it may also work for general
MOAB systems.
"""

from .helpers import runcmd, format_extra_flags

class BatchMOAB:

    def __init__(self, ppn, **attrs):
        """
        The 'variation' keyword can be

            knl : Cray KNL partition
        """
        self.ppn = max( ppn, 1 )
        self.dpn = max( int( attrs.get( 'devices_per_node', 0 ) ), 0 )
        self.variation = attrs.get( 'variation', '' )
        self.extra_flags = format_extra_flags(attrs.get("extra_flags",None))

    def header(self, size, qtime, outfile, plat_attrs):
        """
        """
        np,ndevice = size

        if np <= 0: np = 1
        nnodes = int( np/self.ppn )
        if (np%self.ppn) != 0:
            nnodes += 1

        if self.variation == 'knl':
            hdr = '#MSUB -l nodes='+str(nnodes)+':knl\n'
            hdr += '#MSUB -los=CLE_quad_cache\n'
        else:
            hdr = '#MSUB -l nodes='+str(nnodes) + '\n'
        hdr += '#MSUB -l walltime='+str(qtime) + '\n' + \
               '#MSUB -j oe' + '\n' + \
               '#MSUB -o '+outfile + '\n'

        return hdr


    def submit(self, fname, workdir, outfile, queue=None, account=None):
        """
        Creates and executes a command to submit the given filename as a batch
        job to the resource manager.  Returns (cmd, out, job id, error message)
        where 'cmd' is the submit command executed, 'out' is the output from
        running the command.  The job id is None if an error occured, and error
        message is a string containing the error.  If successful, job id is an
        integer.
        """
        cmdL = ['msub']+self.extra_flags
        if queue != None: cmdL.extend(['-q',queue])
        if account != None: cmdL.extend(['-A',account])
        cmdL.extend(['-o', outfile])
        cmdL.extend(['-j', 'oe'])
        cmdL.extend(['-N', os.path.basename(fname)])
        cmdL.append(fname)
        cmd = ' '.join( cmdL )

        x, out = runcmd( cmdL, workdir )

        # output should contain something like the following
        #    12345.ladmin1 or 12345.sdb
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
        cmdL = ['showq']
        cmd = ' '.join( cmdL )
        x, out = runcmd(cmdL)

        stateD = {}
        for jid in jobidL:
            stateD[jid] = ''  # default to done

        err = ''
        for line in out.strip().split( os.linesep ):
            try:
                L = line.strip().split()
                if len(L) >= 4:
                    jid = L[0]
                    st = L[2]
                    if jid in stateD:
                        if st in ['Running']: st = 'running'
                        elif st in ['Deferred','Idle']: st = 'pending'
                        else: st = ''
                        stateD[jid] = st
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
        if nmin < 10: nmin = '0' + str(nmin)
        else:         nmin = str(nmin)
        return str(nhrs) + ':' + nmin + ':' + nsec
