#!/usr/bin/env python

# Copyright 2018 National Technology & Engineering Solutions of Sandia, LLC
# (NTESS). Under the terms of Contract DE-NA0003525 with NTESS, the U.S.
# Government retains certain rights in this software.

import os
import sys
import time


class BatchJob:

    batchid_counter = 0

    def __init__(self):
        ""
        self.batchid = BatchJob.batchid_counter
        BatchJob.batchid_counter += 1

        self.outfile = None
        self.maxnp = None
        self.jobid = None
        self.wrkdir = None

        self.tstart = None
        self.tseen = None
        self.tstop = None
        self.tcheck = None
        self.result = None

        self.attrs = {}

    def getBatchID(self): return self.batchid
    def getMaxNP(self): return self.maxnp

    def getJobID(self): return self.jobid

    def getWorkDir(self): return self.wrkdir

    def getStartTime(self): return self.tstart
    def getCheckTime(self): return self.tcheck
    def getStopTime(self): return self.tstop

    def getResult(self): return self.result

    def getOutputFilename(self): return self.outfile
    def outfileSeen(self): return self.tseen != None

    def setAttr(self, name, value):
        ""
        self.attrs[name] = value

    def getAttr(self, name, *default):
        ""
        if len(default) > 0:
            return self.attrs.get( name, default[0] )
        return self.attrs[name]

    def setOutputFilename(self, filename):
        ""
        self.outfile = filename

    def setWorkDir(self, dirpath):
        ""
        self.wrkdir = dirpath

    def setMaxNP(self, maxnp):
        ""
        self.maxnp = maxnp

    def setJobID(self, jobid):
        ""
        self.jobid = jobid

    def setStartTime(self, tstart):
        ""
        self.tstart = tstart

    def setOutfileSeen(self, tseen):
        ""
        self.tseen = tseen

    def setCheckTime(self, tcheck):
        ""
        self.tcheck = tcheck

    def setStopTime(self, tstop):
        ""
        self.tstop = tstop

    def setResult(self, result):
        ""
        self.result = result


class BatchQueueInterface:

    def __init__(self):
        ""
        self.batch = None
        self.envD = {}
        self.attrs = {}

        self.clean_exit_marker = "queue job finished cleanly"

    def isBatched(self):
        ""
        return self.batch != None

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
        Set the batch system.  If 'batch' is a string, it must be one of the
        known batch systems, such as

              craypbs   : for Cray machines running PBS (or PBS-like)
              moab      : for Cray machines running Moab (may work in general)
              pbs       : standard PBS system
              slurm     : standard SLURM system

        It can also be a python object which implements the batch functions.
        """
        if type(qtype) == type(''):
            if qtype == 'procbatch':
                from . import procbatch
                self.batch = procbatch.ProcessBatch( ppn )
            elif qtype == 'craypbs':
                from . import craypbs
                self.batch = craypbs.BatchCrayPBS( ppn, **kwargs )
            elif qtype == 'pbs':
                from . import pbs
                self.batch = pbs.BatchPBS( ppn, **kwargs )
            elif qtype == 'slurm':
                from . import slurm
                self.batch = slurm.BatchSLURM( ppn, **kwargs )
            elif qtype == 'moab':
                from . import moab
                self.batch = moab.BatchMOAB( ppn, **kwargs )
            else:
                raise Exception( "Unknown batch system name: "+str(qtype) )
        else:
            self.batch = qtype

        return self.batch

    def writeJobScript(self, np, queue_time, workdir, qout_file,
                             filename, command):
        ""
        qt = self.attrs.get( 'walltime', queue_time )

        hdr = '#!/bin/csh -f\n' + \
              self.batch.header( np, qt, workdir, qout_file, self.attrs ) + '\n'

        if qout_file:
            hdr += 'touch '+qout_file + ' || exit 1\n'

        # add in the shim if specified for this platform
        s = self.attrs.get( 'batchshim', None )
        if s:
            hdr += '\n'+s
        hdr += '\n'

        with open( filename, 'wt' ) as fp:

            fp.writelines( [ hdr + '\n\n',
                             'cd ' + workdir + ' || exit 1\n',
                             'echo "job start time = `date`"\n' + \
                             'echo "job time limit = ' + str(queue_time) + '"\n' ] )

            # set the environment variables from the platform into the script
            for k,v in self.envD.items():
                fp.write( 'setenv ' + k + ' "' + v  + '"\n' )

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


class BatchJobHandler:

    def __init__(self, check_interval, check_timeout, batchitf, namer):
        ""
        self.check_interval = check_interval
        self.check_timeout = check_timeout
        self.batchitf = batchitf
        self.namer = namer

        self.todo  = {}
        self.submitted = {}
        self.stopped  = {}  # not in queue or shown as completed by the queue
        self.done  = {}  # job results have been processed

    def createJob(self):
        ""
        bjob = BatchJob()

        pout = self.namer.getBatchOutputName( bjob.getBatchID() )
        bjob.setOutputFilename( pout )

        bjob.setWorkDir( self.namer.getRootDir() )

        bid = bjob.getBatchID()
        self.todo[ bid ] = bjob

        return bjob

    def writeJobScript(self, batchjob, qtime, cmd):
        ""
        wrkdir = batchjob.getWorkDir()
        pout = batchjob.getOutputFilename()

        fn = self.namer.getBatchScriptName( str( batchjob.getBatchID() ) )

        maxnp = batchjob.getMaxNP()
        self.batchitf.writeJobScript( maxnp, qtime, wrkdir, pout, fn, cmd )

    def startJob(self, batchjob, workdir, scriptname):
        ""
        outfile = batchjob.getOutputFilename()
        jobid = self.batchitf.submitJob( workdir, outfile, scriptname )
        self.markJobStarted( batchjob, jobid )

    def numToDo(self):
        ""
        return len( self.todo )

    def numSubmitted(self):
        return len( self.submitted )

    def numStopped(self):
        return len( self.stopped )

    def numDone(self):
        return len( self.done )

    def getNotStarted(self):
        ""
        return self.todo.values()

    def getStarted(self):
        ""
        return self.submitted.values()

    def getStopped(self):
        ""
        return self.stopped.values()

    def getNotDone(self):
        ""
        for bjob in self.submitted.values():
            yield bjob
        for bjob in self.stopped.values():
            yield bjob

    def getDone(self):
        ""
        return self.done.values()

    def markJobStarted(self, bjob, jobid):
        ""
        tm = time.time()
        bid = bjob.getBatchID()

        self._pop_job( bid )
        self.submitted[ bid ] = bjob

        bjob.setJobID( jobid )
        bjob.setStartTime( tm )
        bjob.setCheckTime( tm )  # magic: may want to make this tm+2

    def markJobStopped(self, bjob):
        ""
        tm = time.time()
        bid = bjob.getBatchID()

        self._pop_job( bid )
        self.stopped[ bid ] = bjob

        bjob.setStopTime( tm )
        bjob.setCheckTime( tm )

    def markJobDone(self, bjob, result):
        ""
        bid = bjob.getBatchID()
        self._pop_job( bid )
        self.done[ bid ] = bjob
        bjob.setResult( result )

    def transitionStartedToStopped(self):
        ""
        doneL = []

        startlist = list( self.getStarted() )

        if len(startlist) > 0:
            jobidL = [ bjob.getJobID() for bjob in startlist ]
            statusD = self.batchitf.queryJobs( jobidL )
            tnow = time.time()
            for bjob in startlist:
                status = statusD[ bjob.getJobID() ]
                if self._check_stopped_job( bjob, status, tnow ):
                    doneL.append( bjob.getBatchID() )

        return doneL

    def _check_stopped_job(self, bjob, queue_status, current_time):
        """
        If job 'queue_status' is empty (meaning the job is not in the queue),
        then return True if enough time has elapsed since the job started or
        the job output file has been seen.
        """
        started = False

        if not queue_status:
            elapsed = current_time - bjob.getStartTime()
            if elapsed > 30 or bjob.outfileSeen():
                started = True
                self.markJobStopped( bjob )

        return started

    def timeToCheckIfFinished(self, bjob, current_time):
        ""
        return current_time > bjob.getCheckTime() + self.check_interval

    def extendFinishCheck(self, bjob, current_time):
        """
        Resets the finish check time to the current time.  Returns
        False if the number of extensions has been exceeded.
        """
        if current_time < bjob.getStopTime()+self.check_timeout:
            bjob.setCheckTime( current_time )
            return True
        else:
            return False

    def scanBatchOutput(self, outfile):
        """
        Tries to read the batch output file, then looks for the marker
        indicating a clean job script finish.  Returns true for a clean finish.
        """
        clean = False

        try:
            # compute file seek offset, and open the file
            sz = os.path.getsize( outfile )
            off = max(sz-512, 0)
            fp = open( outfile, 'r' )
        except Exception:
            pass
        else:
            try:
                # only read the end of the file
                fp.seek(off)
                buf = fp.read(512)
            except Exception:
                pass
            else:
                if self.batchitf.getCleanExitMarker() in buf:
                    clean = True
            try:
                fp.close()
            except Exception:
                pass

        return clean

    def markNotStartedJobsAsDone(self):
        ""
        jobs = []

        for bjob in list( self.getNotStarted() ):
            self.markJobDone( bjob, 'notrun' )
            jobs.append( bjob )

        return jobs

    def getUnfinishedJobIDs(self):
        ""
        notrun = []
        notdone = []
        for bjob in self.getDone():
            bid = str( bjob.getBatchID() )
            if bjob.getResult() == 'notrun':
                notrun.append( bid )
            elif bjob.getResult() == 'notdone':
                notdone.append( bid )

        return notrun, notdone

    def cancelStartedJobs(self):
        ""
        jL = [ bjob.getJobID() for bjob in self.getStarted() ]
        if len(jL) > 0:
            self.batchitf.cancelJobs( jL )

    def _pop_job(self, batchid):
        ""
        for qD in [ self.todo, self.submitted, self.stopped, self.done ]:
            if batchid in qD:
                return qD.pop( batchid )
        raise Exception( 'job id not found: '+str(batchid) )


class BatchFileNamer:

    def __init__(self, rootdir, basename=None):
        ""
        self.rootdir = rootdir
        self.basename = basename

    def getRootDir(self):
        ""
        return self.rootdir

    def getBasePath(self, batchid, relative=False):
        ""
        return self.getPath( self.basename, batchid, relative )

    def getBatchScriptName(self, batchid):
        ""
        return self.getPath( 'qbat', batchid )

    def getBatchOutputName(self, batchid):
        ""
        return self.getPath( 'qbat-out', batchid )

    def getPath(self, basename, batchid, relative=False):
        """
        Given a base file name and a batch id, this function returns the
        file name in the batchset subdirectory and with the id appended.
        If 'relative' is true, then the path is relative to the TestResults
        directory.
        """
        subd = self.getSubdir( batchid, relative )
        if basename == None:
            basename = 'batch'
        fn = os.path.join( subd, basename+'.'+str(batchid) )
        return fn

    def getSubdir(self, batchid, relative=False):
        """
        Given a queue/batch id, this function returns the corresponding
        subdirectory name.  The 'batchid' argument can be a string or integer.
        """
        d = 'batchset' + str( int( float(batchid)/50 + 0.5 ) )
        if relative:
            return d
        return os.path.join( self.rootdir, d )

    def globBatchDirectories(self):
        """
        Returns a list of existing batch working directories.
        """
        dL = []
        for f in os.listdir( self.rootdir ):
            if f.startswith( 'batchset' ):
                dL.append( os.path.join( self.rootdir, f ) )
        return dL


def print3( *args ):
    sys.stdout.write( ' '.join( [ str(arg) for arg in args ] ) + '\n' )
    sys.stdout.flush()
