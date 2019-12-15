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


class Batcher:

    def __init__(self, vvtestcmd, testlist_name,
                       plat, tlist, xlist, perms,
                       test_dir, qsublimit,
                       batch_length, max_timeout):
        ""
        self.plat = plat
        self.perms = perms
        self.maxjobs = qsublimit

        clean_exit_marker = "queue job finished cleanly"

        # allow these values to be set by environment variable, mainly for
        # unit testing; if setting these is needed more regularly then a
        # command line option should be added
        read_interval = int( os.environ.get( 'VVTEST_BATCH_READ_INTERVAL', 30 ) )
        read_timeout = int( os.environ.get( 'VVTEST_BATCH_READ_TIMEOUT', 5*60 ) )

        self.namer = BatchFileNamer( test_dir, testlist_name )

        self.jobmon = BatchJobMonitor( read_interval, read_timeout,
                                       clean_exit_marker )

        self.results = ResultsHandler( tlist, xlist )

        suffix = tlist.getResultsSuffix()
        self.handler = JobHandler( suffix, self.namer, plat,
                                   vvtestcmd,
                                   clean_exit_marker )

        self.grouper = BatchTestGrouper( xlist, batch_length, max_timeout )
        self.grouper.construct()

        self.qsub_testfilenames = []

    def numInFlight(self):
        """
        Returns the number of batch jobs are still running or stopped but
        whose results have not been read yet.
        """
        return self.jobmon.numInFlight()

    def numPastQueue(self):
        ""
        return self.jobmon.numPastQueue()

    def numStarted(self):
        """
        Number of batch jobs currently running (those that have been started
        and still appear to be in the batch queue).
        """
        return self.jobmon.numStarted()

    def numDone(self):
        """
        Number of batch jobs that ran and completed.
        """
        return self.jobmon.numDone()

    def checkstart(self):
        """
        Launches a new batch job if possible.  If it does, the batch id is
        returned.
        """
        if self.jobmon.numStarted() < self.maxjobs:
            for bid,bjob in self.jobmon.getNotStarted():
                if self.results.getBlockingDependency( bjob ) == None:
                    self.startJob( bjob )
                    return bid
        return None

    def startJob(self, bjob):
        ""
        bid = bjob.getBatchID()
        pin = self.namer.getBatchScriptName( bid )
        tdir = self.namer.getRootDir()
        jobid = self.plat.Qsubmit( tdir, bjob.getOutputFile(), pin )
        self.jobmon.markJobStarted( bjob, jobid )

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
        qdoneL = self.checkGetStoppedJobs()
        tdoneL = self.checkGetFinishedTests()

        return qdoneL, tdoneL

    def checkGetStoppedJobs(self):
        ""
        qdoneL = []

        startlist = list( self.jobmon.getStarted() )
        if len(startlist) > 0:
            jobidL = [ bjob.getJobID() for _,bjob in startlist ]
            statusD = self.plat.Qquery( jobidL )
            tnow = time.time()
            for bid,bjob in startlist:
                check_set_outfile_permissions( bjob, self.perms )
                status = statusD[ bjob.getJobID() ]
                if self.jobmon.checkJobStopped( bjob, status, tnow ):
                    qdoneL.append( bid )

        return qdoneL

    def checkGetFinishedTests(self):
        ""
        tnow = time.time()
        tdoneL = []
        for bid,bjob in list( self.jobmon.getStopped() ):
            if self.jobmon.timeToCheckIfFinished( bjob, tnow ):
                tL = self.checkJobFinish( bjob, tnow )
                tdoneL.extend( tL )

        return tdoneL

    def checkJobFinish(self, bjob, current_time):
        ""
        tdoneL = []

        if self.checkForCleanFinish( bjob ):
            tdoneL = self.results.readJobResults( bjob )
            self.jobmon.markJobDone( bjob, 'clean' )

        elif not self.jobmon.extendFinishCheck( bjob, current_time ):
            # too many attempts to read; assume the queue job
            # failed somehow, but force a read anyway
            tdoneL = self.finalizeJob( bjob )

        return tdoneL

    def checkForCleanFinish(self, bjob):
        ""
        ofile = bjob.getOutputFile()
        rfile = bjob.getResultsFile()

        finished = False
        if self.jobmon.scanBatchOutput( ofile ):
            finished = testlistio.file_is_marked_finished( rfile )

        return finished

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
        assert self.jobmon.numInFlight() == 0

        jobL = self.jobmon.markNotStartedJobsAsDone()

        notrunL = []
        for bjob in jobL:
            notrunL.extend( self.results.getFailedDependencies( bjob ) )

        notrun,notdone = self.jobmon.getUnfinishedJobIDs()

        return notrun, notdone, notrunL

    def finalizeJob(self, bjob):
        ""
        tL = []

        if not os.path.exists( bjob.getOutputFile() ):
            mark = 'notrun'

        elif os.path.exists( bjob.getResultsFile() ):
            mark = 'notdone'
            tL.extend( self.results.readJobResults( bjob ) )

        else:
            mark = 'fail'

        self.jobmon.markJobDone( bjob, mark )

        return tL

    def getNumNotRun(self):
        ""
        return self.jobmon.numToDo()

    def getNumStarted(self):
        ""
        return self.jobmon.numStarted()

    def getStarted(self):
        ""
        return self.jobmon.getStarted()

    def writeQsubScripts(self):
        ""
        self._remove_batch_directories()

        for bid,qL in enumerate( self.grouper.getGroups() ):
            self._create_job_and_write_script( bid, qL )

    def getIncludeFiles(self):
        ""
        return self.qsub_testfilenames

    def _remove_batch_directories(self):
        ""
        for d in self.namer.globBatchDirectories():
            print3( 'rm -rf '+d )
            pathutil.fault_tolerant_remove( d )

    def _create_job_and_write_script(self, batchid, testL):
        ""
        bjob = self.handler.createJob( batchid, testL )

        self.jobmon.addJob( bjob )

        qtime = self.grouper.computeQueueTime( bjob.getTestList() )
        self.handler.writeJob( bjob, qtime )

        incl = self.namer.getBasePath( batchid, relative=True )
        self.qsub_testfilenames.append( incl )

        d = self.namer.getSubdir( batchid )
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


class JobHandler:

    def __init__(self, suffix, filenamer, platform,
                       basevvtestcmd, clean_exit_marker):
        ""
        self.suffix = suffix
        self.namer = filenamer
        self.plat = platform
        self.vvtestcmd = basevvtestcmd
        self.clean_exit_marker = clean_exit_marker

    def createJob(self, batchid, testL):
        ""
        testlistfname = self.namer.getBasePath( batchid )
        tlist = make_batch_TestList( testlistfname, self.suffix, testL )

        maxnp = compute_max_np( tlist )

        pout = self.namer.getBatchOutputName( batchid )
        tout = self.namer.getBasePath( batchid ) + '.' + self.suffix

        bjob = BatchJob( batchid, maxnp, pout, tout, tlist )

        return bjob

    def writeJob(self, bjob, qtime):
        ""
        tl = bjob.getTestList()

        tl.stringFileWrite( extended=True )

        bidstr = str( bjob.getBatchID() )
        maxnp = bjob.getMaxNP()

        fn = self.namer.getBatchScriptName( bidstr )
        fp = open( fn, "w" )

        tdir = self.namer.getRootDir()
        pout = self.namer.getBatchOutputName( bjob.getBatchID() )

        hdr = self.plat.getQsubScriptHeader( maxnp, qtime, tdir, pout )
        fp.writelines( [ hdr + '\n\n',
                         'cd ' + tdir + ' || exit 1\n',
                         'echo "job start time = `date`"\n' + \
                         'echo "job time limit = ' + str(qtime) + '"\n' ] )

        # set the environment variables from the platform into the script
        for k,v in self.plat.getEnvironment().items():
            fp.write( 'setenv ' + k + ' "' + v  + '"\n' )

        cmd = self.vvtestcmd + ' --qsub-id=' + bidstr

        if len( tl.getTestMap() ) == 1:
            # force a timeout for batches with only one test
            if qtime < 600: cmd += ' -T ' + str(qtime*0.90)
            else:           cmd += ' -T ' + str(qtime-120)

        cmd += ' || exit 1'
        fp.writelines( [ cmd+'\n\n' ] )

        # echo a marker to determine when a clean batch job exit has occurred
        fp.writelines( [ 'echo "'+self.clean_exit_marker+'"\n' ] )

        fp.close()


class ResultsHandler:

    def __init__(self, tlist, xlist):
        ""
        self.tlist = tlist
        self.xlist = xlist

    def readJobResults(self, bjob):
        ""
        tL = []

        self.tlist.readTestResults( bjob.getResultsFile() )

        tlr = testlistio.TestListReader( bjob.getResultsFile() )
        tlr.read()
        jobtests = tlr.getTests()

        # only add tests to the stopped list that are done
        for tcase in bjob.getTests():

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
        for tcase0 in bjob.getTests():
            depL.append( (tcase0,tcase1) )

        return depL

    def getBlockingDependency(self, bjob):
        """
        If a dependency of any of the tests in the current list have not run or
        ran but did not pass or diff, then that dependency test is returned.
        Otherwise None is returned.
        """
        for tcase in bjob.getTests():
            deptx = tcase.getBlockingDependency()
            if deptx != None:
                return deptx
        return None


def check_set_outfile_permissions( bjob, perms ):
    ""
    ofile = bjob.getOutputFile()
    if not bjob.outfileSeen() and os.path.exists( ofile ):
        perms.set( ofile )
        bjob.setOutfileSeen()


class BatchJob:

    def __init__(self, batchid, maxnp, fout, resultsfile, tlist):
        ""
        self.batchid = batchid
        self.maxnp = maxnp
        self.outfile = fout
        self.resultsfile = resultsfile
        self.tlist = tlist  # a TestList object

        self.jobid = None
        self.tstart = None
        self.outfile_seen = False
        self.tstop = None
        self.tcheck = None
        self.result = None

    def getBatchID(self): return self.batchid
    def getMaxNP(self): return self.maxnp

    def getTestList(self): return self.tlist
    def getTests(self): return self.tlist.getTests()

    def getJobID(self): return self.jobid

    def getStartTime(self): return self.tstart
    def getCheckTime(self): return self.tcheck
    def getStopTime(self): return self.tstop

    def getResult(self): return self.result

    def getOutputFile(self): return self.outfile
    def outfileSeen(self): return self.outfile_seen
    def getResultsFile(self): return self.resultsfile

    def setJobID(self, jobid):
        ""
        self.jobid = jobid

    def setStartTime(self, tstart):
        ""
        self.tstart = tstart

    def setOutfileSeen(self):
        ""
        self.outfile_seen = True

    def setCheckTime(self, tcheck):
        ""
        self.tcheck = tcheck

    def setStopTime(self, tstop):
        ""
        self.tstop = tstop

    def setResult(self, result):
        ""
        self.result = result


class BatchJobMonitor:

    def __init__(self, read_interval, read_timeout, clean_exit_marker):
        ""
        self.read_interval = read_interval
        self.read_timeout = read_timeout
        self.clean_exit_marker = clean_exit_marker

        self.qtodo  = {}  # to be submitted
        self.qstart = {}  # submitted
        self.qstop  = {}  # no longer in the queue
        self.qdone  = {}  # final results have been read

    def addJob(self, batchjob ):
        ""
        bid = batchjob.getBatchID()
        self.qtodo[ bid ] = batchjob

    def numToDo(self):
        ""
        return len( self.qtodo )

    def numStarted(self):
        return len( self.qstart )

    def numDone(self):
        return len( self.qdone )

    def numInFlight(self):
        return len( self.qstart ) + len( self.qstop )

    def numPastQueue(self):
        return len( self.qstop ) + len( self.qdone )

    def getNotStarted(self):
        ""
        return self.qtodo.items()

    def getStarted(self):
        ""
        return self.qstart.items()

    def getStopped(self):
        ""
        return self.qstop.items()

    def getDone(self):
        ""
        return self.qdone.items()

    def markJobStarted(self, bjob, jobid):
        ""
        tm = time.time()
        bid = bjob.getBatchID()

        self._pop_job( bid )
        self.qstart[ bid ] = bjob

        bjob.setJobID( jobid )
        bjob.setStartTime( tm )

    def markJobStopped(self, bjob):
        ""
        tm = time.time()
        bid = bjob.getBatchID()

        self._pop_job( bid )
        self.qstop[ bid ] = bjob

        bjob.setStopTime( tm )
        bjob.setCheckTime( tm + self.read_interval )

    def markJobDone(self, bjob, result):
        ""
        bid = bjob.getBatchID()
        self._pop_job( bid )
        self.qdone[ bid ] = bjob
        bjob.setResult( result )

    def checkJobStopped(self, bjob, queue_status, current_time):
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
        return bjob.getCheckTime() < current_time

    def extendFinishCheck(self, bjob, current_time):
        """
        Resets the finish check time to a time into the future.  Returns
        False if the number of extensions has been exceeded.
        """
        if current_time < bjob.getStopTime()+self.read_timeout:
            # set the time for the next read attempt
            bjob.setCheckTime( current_time + self.read_interval )
            return False

        return True

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
                if self.clean_exit_marker in buf:
                    clean = True
            try:
                fp.close()
            except Exception:
                pass

        return clean

    def markNotStartedJobsAsDone(self):
        ""
        jobs = []

        for bid,bjob in list( self.getNotStarted() ):
            self.markJobDone( bjob, 'notrun' )
            jobs.append( bjob )

        return jobs

    def getUnfinishedJobIDs(self):
        ""
        notrun = []
        notdone = []
        for bid,bjob in self.getDone():
            if bjob.getResult() == 'notrun': notrun.append( str(bid) )
            elif bjob.getResult() == 'notdone': notdone.append( str(bid) )

        return notrun, notdone

    def _pop_job(self, batchid):
        ""
        for qD in [ self.qtodo, self.qstart, self.qstop, self.qdone ]:
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
