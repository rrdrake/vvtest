#!/usr/bin/env python

# Copyright 2018 National Technology & Engineering Solutions of Sandia, LLC
# (NTESS). Under the terms of Contract DE-NA0003525 with NTESS, the U.S.
# Government retains certain rights in this software.

import sys
import os
import time
import glob

from . import TestList
from . import testlistio
from . import pathutil
from . import batching


class Batcher:

    def __init__(self, vvtestcmd,
                       tlist, xlist, perms,
                       qsublimit,
                       batch_length, max_timeout,
                       namer, jobhandler):
        ""
        self.perms = perms
        self.maxjobs = qsublimit

        self.namer = namer
        self.jobhandler = jobhandler

        self.results = ResultsHandler( tlist, xlist )

        self.suffix = tlist.getResultsSuffix()
        self.vvtestcmd = vvtestcmd

        self.grouper = BatchTestGrouper( xlist, batch_length, max_timeout )

        self.qsub_testfilenames = []

    def writeQsubScripts(self):
        ""
        self._remove_batch_directories()

        self.grouper.construct()
        for qL in self.grouper.getGroups():
            bjob = self.jobhandler.createJob()
            self._construct_job( bjob, qL )

    def getNumNotRun(self):
        ""
        return self.jobhandler.numToDo()

    def getNumStarted(self):
        """
        Number of batch jobs currently running (those that have been started
        and still appear to be in the batch queue).
        """
        return self.jobhandler.numSubmitted()

    def numInProgress(self):
        """
        Returns the number of batch jobs are still running or stopped but
        whose results have not been read yet.
        """
        return self.jobhandler.numSubmitted() + self.jobhandler.numStopped()

    def numPastQueue(self):
        ""
        return self.jobhandler.numStopped() + self.jobhandler.numDone()

    def getNumDone(self):
        """
        Number of batch jobs that ran and completed.
        """
        return self.jobhandler.numDone()

    def getStarted(self):
        ""
        return self.jobhandler.getStarted()

    def checkstart(self):
        """
        Launches a new batch job if possible.  If it does, the batch id is
        returned.
        """
        if self.jobhandler.numSubmitted() < self.maxjobs:
            for bjob in self.jobhandler.getNotStarted():
                if self.results.getBlockingDependency( bjob ) == None:
                    self._start_job( bjob )
                    return bjob.getBatchID()
        return None

    def checkdone(self):
        """
        Uses the platform to find batch jobs that ran but are now no longer
        in the batch queue.  These jobs are moved from the started list to
        the stopped list.

        Then the jobs in the "stopped" list are visited and their test
        results are read.  When a job is successfully read, the job is moved
        from the "stopped" list to the "read" list.

        Returns a list of job ids that were removed from the batch queue,
        and a list of tests that were successfully read in.
        """
        qdoneL = self._check_get_stopped_jobs()
        tdoneL = self._check_get_finished_tests()

        return qdoneL, tdoneL

    def flush(self):
        """
        Remove any remaining jobs from the "todo" list, add them to the "read"
        list, but mark them as not run.

        Returns a triple
            - a list of batch ids that were not run
            - a list of batch ids that did not finish
            - a list of the tests that did not run, each of which is a
              pair (a test, failed dependency test)
        """
        # should not be here if there are jobs currently running
        assert self.numInProgress() == 0

        jobL = self.jobhandler.markNotStartedJobsAsDone()

        notrunL = []
        for bjob in jobL:
            notrunL.extend( self.results.getFailedDependencies( bjob ) )

        notrun,notdone = self.jobhandler.getUnfinishedJobIDs()

        return notrun, notdone, notrunL

    def getIncludeFiles(self):
        ""
        return self.qsub_testfilenames

    def cancelJobs(self):
        ""
        self.jobhandler.cancelStartedJobs()

    #####################################################################

    def _start_job(self, bjob):
        ""
        self._write_job( bjob )

        bid = bjob.getBatchID()
        pin = self.namer.getBatchScriptName( bid )
        tdir = self.namer.getRootDir()
        self.jobhandler.startJob( bjob, tdir, pin )

    def _check_get_stopped_jobs(self):
        ""
        tm = time.time()
        for bjob in self.jobhandler.getStarted():
            check_set_outfile_permissions( bjob, self.perms, tm )

        done_jobids = self.jobhandler.transitionStartedToStopped()

        return done_jobids

    def _check_get_finished_tests(self):
        ""
        tnow = time.time()
        tdoneL = []
        for bjob in list( self.jobhandler.getStopped() ):
            if self.jobhandler.timeToCheckIfFinished( bjob, tnow ):
                tL = self._check_job_finish( bjob, tnow )
                tdoneL.extend( tL )

        return tdoneL

    def _check_job_finish(self, bjob, current_time):
        ""
        tdoneL = []

        if self._check_for_clean_finish( bjob ):
            tdoneL = self.results.readJobResults( bjob )
            self.jobhandler.markJobDone( bjob, 'clean' )

        elif not self.jobhandler.extendFinishCheck( bjob, current_time ):
            # too many attempts to read; assume the queue job
            # failed somehow, but force a read anyway
            tdoneL = self._finish_job( bjob )

        return tdoneL

    def _check_for_clean_finish(self, bjob):
        ""
        ofile = bjob.getOutputFilename()
        rfile = bjob.getAttr('resultsfilename')

        finished = False
        if self.jobhandler.scanBatchOutput( ofile ):
            finished = testlistio.file_is_marked_finished( rfile )

        return finished

    def _finish_job(self, bjob):
        ""
        tL = []

        if not os.path.exists( bjob.getOutputFilename() ):
            mark = 'notrun'

        elif os.path.exists( bjob.getAttr('resultsfilename') ):
            mark = 'notdone'
            tL.extend( self.results.readJobResults( bjob ) )

        else:
            mark = 'fail'

        self.jobhandler.markJobDone( bjob, mark )

        return tL

    def _remove_batch_directories(self):
        ""
        for d in self.namer.globBatchDirectories():
            print3( 'rm -rf '+d )
            pathutil.fault_tolerant_remove( d )

    def _construct_job(self, bjob, testL):
        ""
        testlistfname = self.namer.getBasePath( bjob.getBatchID() )
        tlist = make_batch_TestList( testlistfname, self.suffix, testL )

        maxnp = compute_max_np( tlist )

        bjob.setMaxNP( maxnp )
        bjob.setAttr( 'testlist', tlist )

        rfile = self.namer.getBasePath( bjob.getBatchID() )+'.'+self.suffix
        bjob.setAttr( 'resultsfilename', rfile )

        incl = self.namer.getBasePath( bjob.getBatchID(), relative=True )
        self.qsub_testfilenames.append( incl )

    def _write_job(self, bjob):
        ""
        qtime = self.grouper.computeQueueTime( bjob.getAttr('testlist') )

        tl = bjob.getAttr('testlist')

        tl.stringFileWrite( extended=True )

        cmd = self.vvtestcmd + ' --qsub-id='+str( bjob.getBatchID() )

        if len( tl.getTestMap() ) == 1:
            # force a timeout for batches with only one test
            if qtime < 600: cmd += ' -T ' + str(qtime*0.90)
            else:           cmd += ' -T ' + str(qtime-120)

        cmd += ' || exit 1'

        self.jobhandler.writeJobScript( bjob, qtime, cmd )

        d = self.namer.getSubdir( bjob.getBatchID() )
        self.perms.recurse( d )


class BatchTestGrouper:

    def __init__(self, xlist, batch_length, max_timeout):
        ""
        self.xlist = xlist

        if batch_length == None:
            self.qlen = 30*60
        else:
            self.qlen = batch_length

        self.max_timeout = max_timeout

        # TODO: make Tzero a platform plugin thing
        self.Tzero = 21*60*60  # no timeout in batch mode is 21 hours

        self.groups = []

    def construct(self):
        ""
        qL = []

        for np in self.xlist.getTestExecProcList():
            qL.extend( self._process_groups( np ) )

        qL.sort()
        qL.reverse()

        self.groups = [ L[3] for L in qL ]

    def getGroups(self):
        ""
        return self.groups

    def computeQueueTime(self, tlist):
        ""
        qtime = 0

        for tcase in tlist.getTests():
            tspec = tcase.getSpec()
            qtime += int( tspec.getAttr('timeout') )

        if qtime == 0:
            qtime = self.Tzero  # give it the "no timeout" length of time
        else:
            qtime = apply_queue_timeout_bump_factor( qtime )

        if self.max_timeout:
            qtime = min( qtime, float(self.max_timeout) )

        return qtime

    def _process_groups(self, np):
        ""
        qL = []

        xL = []
        for tcase in self.xlist.getTestExecList(np):
            xdir = tcase.getSpec().getDisplayString()
            xL.append( (tcase.getSpec().getAttr('timeout'),xdir,tcase) )
        xL.sort()

        grpL = []
        tsum = 0
        for rt,xdir,tcase in xL:
            tspec = tcase.getSpec()
            if tcase.numDependencies() > 0 or tspec.getAttr('timeout') < 1:
                # analyze tests and those with no timeout get their own group
                qL.append( [ self.Tzero, np, len(qL), [tcase] ] )
            else:
                if len(grpL) > 0 and tsum + rt > self.qlen:
                    qL.append( [ tsum, np, len(qL), grpL ] )
                    grpL = []
                    tsum = 0
                grpL.append( tcase )
                tsum += rt

        if len(grpL) > 0:
            qL.append( [ tsum, np, len(qL), grpL ] )

        return qL


def make_batch_TestList( filename, suffix, qlist ):
    ""
    tl = TestList.TestList( filename )
    tl.setResultsSuffix( suffix )
    for tcase in qlist:
        tl.addTest( tcase )

    return tl


def compute_max_np( tlist ):
    ""
    maxnp = 0
    for tcase in tlist.getTests():
        tspec = tcase.getSpec()
        np = int( tspec.getParameters().get('np', 0) )
        if np <= 0: np = 1
        maxnp = max( maxnp, np )

    return maxnp


def apply_queue_timeout_bump_factor( qtime ):
    ""
    # allow more time in the queue than calculated. This overhead time
    # monotonically increases with increasing qtime and plateaus at
    # about 16 minutes of overhead, but force it to never be more than
    # exactly 15 minutes.

    if qtime < 60:
        qtime += 60
    elif qtime < 10*60:
        qtime += qtime
    elif qtime < 30*60:
        qtime += min( 15*60, 10*60 + int( float(qtime-10*60) * 0.3 ) )
    else:
        qtime += min( 15*60, 10*60 + int( float(30*60-10*60) * 0.3 ) )

    return qtime


class ResultsHandler:

    def __init__(self, tlist, xlist):
        ""
        self.tlist = tlist
        self.xlist = xlist

    def readJobResults(self, bjob):
        ""
        tL = []

        rfile = bjob.getAttr('resultsfilename')
        self.tlist.readTestResults( rfile )

        tlr = testlistio.TestListReader( rfile )
        tlr.read()
        jobtests = tlr.getTests()

        # only add tests to the stopped list that are done
        for tcase in bjob.getAttr('testlist').getTests():

            tid = tcase.getSpec().getID()

            job_tcase = jobtests.get( tid, None )
            if job_tcase and job_tcase.getStat().isDone():
                tL.append( tcase )
                self.xlist.testDone( tcase )

        return tL

    def getFailedDependencies(self, bjob):
        ""
        depL = []

        tcase1 = self.getBlockingDependency( bjob )
        assert tcase1 != None  # otherwise the job should have run
        for tcase0 in bjob.getAttr('testlist').getTests():
            depL.append( (tcase0,tcase1) )

        return depL

    def getBlockingDependency(self, bjob):
        """
        If a dependency of any of the tests in the current list have not run or
        ran but did not pass or diff, then that dependency test is returned.
        Otherwise None is returned.
        """
        for tcase in bjob.getAttr('testlist').getTests():
            deptx = tcase.getBlockingDependency()
            if deptx != None:
                return deptx
        return None


def check_set_outfile_permissions( bjob, perms, curtime ):
    ""
    ofile = bjob.getOutputFilename()
    if not bjob.outfileSeen() and os.path.exists( ofile ):
        perms.set( ofile )
        bjob.setOutfileSeen( curtime )


def print3( *args ):
    sys.stdout.write( ' '.join( [ str(arg) for arg in args ] ) + '\n' )
    sys.stdout.flush()
