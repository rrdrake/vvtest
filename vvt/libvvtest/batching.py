#!/usr/bin/env python

# Copyright 2018 National Technology & Engineering Solutions of Sandia, LLC
# (NTESS). Under the terms of Contract DE-NA0003525 with NTESS, the U.S.
# Government retains certain rights in this software.

import os
import sys
import time


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

    def getCleanExitMarker(self):
        ""
        return self.clean_exit_marker

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
