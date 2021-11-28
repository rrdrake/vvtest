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

    def __init__(self):
        ""
        self.batch = None
        self.envD = {}
        self.attrs = {}

        self.clean_exit_marker = "queue job finished cleanly"

    def isBatched(self):
        ""
        return self.batch is not None

    def getNodeSize(self):
        ""
        np = self.attrs.get( 'ppn', self.attrs.get( 'processors_per_node', None ) )
        nd = self.attrs.get( 'dpn', self.attrs.get( 'devices_per_node', None ) )
        return np,nd

    def getCleanExitMarker(self):
        ""
        return self.clean_exit_marker

    def setAttr(self, name, value):
        ""
        self.attrs[name] = value

    def setEnviron(self, name, value):
        ""
        self.envD[name] = value

    def setQueueType(self, qtype, ppn, **kwargs):
        """
        Set the batch system to one of these values:

              slurm     : standard SLURM system
              lsf       : LSF, such as the Sierra platform
              craypbs   : for Cray machines running PBS (or PBS-like)
              moab      : for Cray machines running Moab (may work in general)
              pbs       : standard PBS system
        """
        assert type(qtype) == type('')

        self.batch = batch_queue_factory( qtype, ppn, self.attrs )

        self.setAttr( 'ppn', ppn )

        return self.batch

    def writeJobScript(self, size, queue_time, workdir, qout_file,
                             filename, command):
        ""
        qt = self.attrs.get( 'walltime', queue_time )

        hdr = '#!/bin/bash\n' + \
              self.batch.header( size, qt, qout_file, self.attrs ) + '\n'

        hdr += 'cd '+quote(workdir)+' || exit 1\n'

        if qout_file:
            hdr += 'touch '+qout_file + ' || exit 1\n'

        hdr += '\n'

        with open( filename, 'wt' ) as fp:

            fp.writelines( [ hdr + '\n\n',
                             'echo "job start time = `date`"\n' + \
                             'echo "job time limit = ' + str(queue_time) + '"\n' ] )

            # set the environment variables from the platform into the script
            for k,v in self.envD.items():
                fp.write( 'export ' + k + '="' + v  + '"\n' )

            fp.writelines( [ command+'\n\n' ] )

            # echo a marker to determine when a clean batch job exit has occurred
            fp.writelines( [ 'echo "'+self.clean_exit_marker+'"\n' ] )

    def submitJob(self, workdir, outfile, scriptname):
        ""
        q = self.attrs.get( 'queue', None )
        acnt = self.attrs.get( 'account', None )
        cmd, out, jobid, err = \
                self.batch.submit( scriptname, workdir, outfile, q, acnt )
        if err:
            print3( cmd + os.linesep + out + os.linesep + err )
        else:
            print3( "Job script", scriptname, "submitted with id", jobid )

        return jobid

    def queryJobs(self, jobidL):
        ""
        cmd, out, err, jobD = self.batch.query( jobidL )
        if err:
            print3( cmd + os.linesep + out + os.linesep + err )

        return jobD

    def cancelJobs(self, jobidL):
        ""
        if hasattr( self.batch, 'cancel' ):
            print3( '\nCancelling jobs:', jobidL )
            for jid in jobidL:
                self.batch.cancel( jid )


def batch_queue_factory( qtype, ppn, batchattrs ):
    ""
    if qtype == 'procbatch':
        from . import procbatch
        batch = procbatch.ProcessBatch( ppn, **batchattrs )
    elif qtype == 'craypbs':
        from . import craypbs
        batch = craypbs.BatchCrayPBS( ppn, **batchattrs )
    elif qtype == 'pbs':
        from . import pbs
        batch = pbs.BatchPBS( ppn, **batchattrs )
    elif qtype == 'slurm':
        from . import slurm
        batch = slurm.BatchSLURM( ppn, **batchattrs )
    elif qtype == 'moab':
        from . import moab
        batch = moab.BatchMOAB( ppn, **batchattrs )
    elif qtype == 'lsf':
        from . import lsf
        batch = lsf.BatchLSF( ppn, **batchattrs )
    else:
        raise Exception( "Unknown batch system name: "+str(qtype) )

    return batch


def print3( *args ):
    sys.stdout.write( ' '.join( [ str(arg) for arg in args ] ) + '\n' )
    sys.stdout.flush()
