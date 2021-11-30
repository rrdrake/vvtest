#!/usr/bin/env python

# Copyright 2018 National Technology & Engineering Solutions of Sandia, LLC
# (NTESS). Under the terms of Contract DE-NA0003525 with NTESS, the U.S.
# Government retains certain rights in this software.

import os, sys
import time

from .helpers import runcmd, compute_num_nodes, format_extra_flags, get_node_size

class BatchSLURM:

    def __init__(self, **attrs):
        ""
        self.attrs = attrs
        self.ppn,self.dpn = get_node_size( attrs )

        args = format_extra_flags( attrs.get("extra_flags",None) )
        args.extend( self._attr_to_option( 'queue',   '--partition' ) )
        args.extend( self._attr_to_option( 'account', '--account' ) )
        args.extend( self._attr_to_option( 'QoS',     '--qos' ) )
        self.submit_args = args

        self.runcmd = runcmd

    def _attr_to_option(self, attr_name, option_name):
        ""
        if attr_name in self.attrs and self.attrs[attr_name] is not None:
            return [ option_name+'='+self.attrs[attr_name] ]
        return []

    def setRunCommand(self, run_function):
        ""
        self.runcmd = run_function

    def header(self, size, qtime, outfile):
        ""
        nnodes = compute_num_nodes( size, self.ppn, self.dpn )

        hdr = '#SBATCH --time=' + self.HMSformat(qtime) + '\n' + \
              '#SBATCH --nodes=' + str(nnodes) + '\n' + \
              '#SBATCH --output=' + outfile + '\n' + \
              '#SBATCH --error=' + outfile + '\n'

        return hdr

    def submit(self, fname, outfile):
        """
        Creates and executes a command to submit the given filename as a batch
        job to the resource manager.  Returns (cmd, out, job id, error message)
        where 'cmd' is the submit command executed, 'out' is the output from
        running the command.  The job id is None if an error occured, and error
        message is a string containing the error.
        """
        cmdL = ['sbatch']+self.submit_args
        cmdL.append('--output='+outfile)
        cmdL.append('--error='+outfile)
        cmdL.append(fname)

        cmdstr = ' '.join( cmdL )

        x, out = self.runcmd( cmdL )

        # output should contain something like the following
        #    sbatch: Submitted batch job 291041
        jobid = None
        i = out.find( "Submitted batch job" )
        if i >= 0:
            L = out[i:].split()
            if len(L) > 3:
                try:
                    jobid = int(L[3])
                except Exception:
                    if L[3]:
                        jobid = L[3]
                    else:
                        jobid = None

        if jobid == None:
            return cmdstr, out, None, \
                "batch submission failed or could not parse " + \
                "output to obtain the job id"

        return cmdstr, out, jobid, ""

    def query(self, jobidL):
        """
        Determine the state of the given job ids.  Returns (cmd, out, err, stateD)
        where stateD is dictionary mapping the job ids to a string equal to
        'pending', 'running', or '' (empty) and empty means either the job was
        not listed or it was listed but not pending or running.  The err value
        contains an error message if an error occurred when getting the states.
        """
        cmdL = ['squeue', '--noheader', '-o', '%i %t']
        cmdstr = ' '.join( cmdL )
        x, out = self.runcmd(cmdL)

        stateD = {}
        for jid in jobidL:
            stateD[jid] = ''  # default to done

        err = ''
        for line in out.strip().split( os.linesep ):
            try:
                L = line.split()
                if len(L) > 0:
                    try:
                        jid = int(L[0])
                    except Exception:
                        if L[0]:
                            jid = L[0]
                        else:
                            raise
                    st = L[1]
                    if jid in stateD:
                        if st in ['R']: st = 'running'
                        elif st in ['PD']: st = 'pending'
                        else: st = ''
                        stateD[jid] = st
            except Exception:
                e = sys.exc_info()[1]
                err = "failed to parse squeue output: " + str(e)

        return cmdstr, out, err, stateD

    def cancel(self, jobid):
        ""
        print ( 'scancel '+str(jobid) )
        x, out = self.runcmd( [ 'scancel', str(jobid) ] )

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
