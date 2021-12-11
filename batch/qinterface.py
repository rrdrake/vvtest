#!/usr/bin/env python

# Copyright 2018 National Technology & Engineering Solutions of Sandia, LLC
# (NTESS). Under the terms of Contract DE-NA0003525 with NTESS, the U.S.
# Government retains certain rights in this software.

import os
import sys

try:
    from shlex import quote
except Exception:
    from pipes import quote


class BatchQueueInterface:

    def __init__(self, attrs={}, envD={}):
        """
        The 'attrs' must have a "batchsys" key with one of these values:

            slurm     : standard SLURM system
            lsf       : LSF, such as the Sierra platform
            craypbs   : for Cray machines running PBS (or PBS-like)
            moab      : for Cray machines running Moab (may work in general)
            pbs       : standard PBS system
            procbatch : simulate batch processing with subprocesses
        """
        self.batch = None
        self.attrs = dict( attrs )
        self.envD = dict( envD )

        assert 'batchsys' in self.attrs
        assert self.attrs['ppn'] and self.attrs['ppn'] > 0
        self.batch = batch_system_factory( self.attrs )

        self.clean_exit_marker = "queue job finished cleanly"

    def getNodeSize(self):
        ""
        np = self.attrs.get( 'ppn', None )
        nd = self.attrs.get( 'dpn', None )
        return np,nd

    def getCleanExitMarker(self):
        ""
        return self.clean_exit_marker

    def writeJobScript(self, size, queue_time, workdir, qout_file,
                             filename, command):
        ""
        qt = self.attrs.get( 'walltime', queue_time )

        bufL = [ '#!/bin/bash' ]

        bhead = self.batch.header( size, qt, qout_file )
        if type(bhead) == type(''):
            bufL.append( bhead )
        else:
            bufL.extend( list(bhead) )

        bufL.extend( [ '# attributes: '+str(self.attrs),
                       '',
                       'cd '+quote(workdir)+' || exit 1' ] )
        if qout_file:
            bufL.append( 'touch '+quote(qout_file) + ' || exit 1' )

        bufL.extend( [ '',
                       'echo "job start time = `date`"',
                       'echo "job time limit = '+str(queue_time)+'"' ] )

        # set the environment variables from the platform into the script
        for k,v in self.envD.items():
            bufL.append( 'export '+k+'="'+v +'"' )

        bufL.extend( [ '',
                       command,
                       '',
                       'echo "'+self.clean_exit_marker+'"' ] )

        with open( filename, 'wt' ) as fp:
            fp.write( '\n'.join( bufL ) + '\n' )

    def submitJob(self, workdir, outfile, scriptname):
        ""
        cwd = os.getcwd()
        os.chdir( workdir )
        try:
            jobid,cmd,out = self.batch.submit( scriptname, outfile )
        finally:
            os.chdir( cwd )

        if jobid is None:
            print3( cmd+'\n'+out )
            print3( '*** Batch submission failed or could not parse '
                    'output to get job id' )
        else:
            print3( "Job script", scriptname, "submitted with id", jobid )

        return jobid

    def queryJobs(self, jobidL):
        """
        returns a dict mapping jobid to a string, where the string is empty if
        the jobid is not in the queue (or is done), or "running" or "pending"
        """
        jobD,cmd,out = self.batch.query( jobidL )

        for jobid in jobidL:
            if jobid not in jobD:
                jobD[jobid] = ''

        return jobD

    def cancelJobs(self, jobidL):
        ""
        if hasattr( self.batch, 'cancel' ):
            print3( '\nCancelling jobs:', jobidL )
            for jid in jobidL:
                self.batch.cancel( jid )


def batch_system_factory( batchattrs ):
    ""
    qtype = batchattrs['batchsys']

    if qtype == 'procbatch':
        from . import procbatch
        batch = procbatch.SubProcs( **batchattrs )
    elif qtype == 'craypbs':
        from . import craypbs
        batch = craypbs.BatchCrayPBS( **batchattrs )
    elif qtype == 'pbs':
        from . import pbs
        batch = pbs.BatchPBS( **batchattrs )
    elif qtype == 'slurm':
        from . import slurm
        batch = slurm.BatchSLURM( **batchattrs )
    elif qtype == 'moab':
        from . import moab
        batch = moab.BatchMOAB( **batchattrs )
    elif qtype == 'lsf':
        from . import lsf
        batch = lsf.BatchLSF( **batchattrs )
    else:
        raise Exception( "Unknown batch system name: "+str(qtype) )

    return batch


def print3( *args ):
    sys.stdout.write( ' '.join( [ str(arg) for arg in args ] ) + '\n' )
    sys.stdout.flush()
