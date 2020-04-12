#!/usr/bin/env python

# Copyright 2018 National Technology & Engineering Solutions of Sandia, LLC
# (NTESS). Under the terms of Contract DE-NA0003525 with NTESS, the U.S.
# Government retains certain rights in this software.

import os, sys

from .TestExec import TestExec
from . import depend
from .teststatus import copy_test_results


class TestExecList:

    def __init__(self, tlist, runner):
        ""
        self.tlist = tlist
        self.runner = runner

        self.backlog = TestBacklog()
        self.waiting = {}  # TestSpec ID -> TestCase object
        self.started = {}  # TestSpec ID -> TestCase object
        self.stopped = {}  # TestSpec ID -> TestCase object

    def createTestExecs(self):
        """
        Creates the set of TestExec objects from the active test list.
        """
        self._generate_backlog_from_testlist()
        self.sortBySizeAndRuntime()  # sorts tests by longest running first
        self._connect_execute_dependencies()

        for tcase in self.backlog.iterate():
            self.runner.initialize_for_execution( tcase )

    def _generate_backlog_from_testlist(self):
        ""
        for tcase in self.tlist.getTests():
            if not tcase.getStat().skipTest():
                assert tcase.getSpec().constructionCompleted()
                tcase.setExec( TestExec() )
                self.backlog.insert( tcase )

    def _connect_execute_dependencies(self):
        ""
        tmap = self.tlist.getTestMap()
        groups = self.tlist.getGroupMap()

        for tcase in self.backlog.iterate():

            if tcase.getSpec().isAnalyze():
                grpL = groups.getGroup( tcase )
                depend.connect_analyze_dependencies( tcase, grpL, tmap )

            depend.check_connect_dependencies( tcase, tmap )

    def sortBySizeAndRuntime(self):
        """
        Sort the TestExec objects by runtime, descending order.  This is so
        popNext() will try to avoid launching long running tests at the end
        of the testing sequence, which can add significantly to the total wall
        time.
        """
        self.backlog.sort()

    def sortBySizeAndTimeout(self):
        ""
        self.backlog.sort( secondary='timeout' )

    def getNextTest(self):
        ""
        tcase = self.backlog.pop()

        if tcase != None:
            self.waiting[ tcase.getSpec().getID() ] = tcase

        return tcase

    def popNext(self, platform):
        """
        Finds a test to execute.  Returns a TestExec object, or None if no
        test can run.  In this case, one of the following is true

            1. there are not enough free processors to run another test
            2. the only tests left have a dependency with a bad result (like
               a fail) preventing the test from running

        In the latter case, numRunning() will be zero.
        """
        # find longest runtime test with size constraint
        tcase = self._pop_next_test( platform )
        if tcase == None and len(self.started) == 0:
            # find longest runtime test without size constraint
            tcase = self._pop_next_test()

        return tcase

    def consumeBacklog(self):
        ""
        for tcase in self.backlog.consume():
            self.waiting[ tcase.getSpec().getID() ] = tcase
            yield tcase

    def startTest(self, tcase, platform, baseline=0):
        ""
        self.moveToStarted( tcase )

        tspec = tcase.getSpec()
        texec = tcase.getExec()

        np = int( tspec.getParameters().get('np', 0) )

        obj = platform.obtainProcs( np )
        texec.setResourceObject( obj )

        texec.start( baseline )

        tcase.getStat().markStarted( texec.getStartTime() )

    def moveToStarted(self, tcase):
        ""
        tid = tcase.getSpec().getID()

        self.waiting.pop( tid )
        self.started[ tid ] = tcase

    def popRemaining(self):
        """
        All remaining tests are removed from the backlog and returned.
        """
        return [ tcase for tcase in self.backlog.consume() ]

    def getRunning(self):
        """
        Return the list of TestCase that are still running.
        """
        return self.started.values()

    def testDone(self, tcase):
        ""
        xid = tcase.getSpec().getID()
        self.tlist.appendTestResult( tcase )
        self.started.pop( xid, None )
        self.stopped[ xid ] = tcase

    def numDone(self):
        """
        Return the number of tests that have been run.
        """
        return len(self.stopped)

    def numRunning(self):
        """
        Return the number of tests are currently running.
        """
        return len(self.started)

    def checkStateChange(self, tmp_tcase):
        ""
        tid = tmp_tcase.getSpec().getID()

        tcase = None

        if tid in self.waiting:
            if tmp_tcase.getStat().isNotDone():
                tcase = self.waiting.pop( tid )
                self.started[ tid ] = tcase
            elif tmp_tcase.getStat().isDone():
                tcase = self.waiting.pop( tid )
                self.stopped[ tid ] = tcase

        elif tid in self.started:
            if tmp_tcase.getStat().isDone():
                tcase = self.started.pop( tid )
                self.stopped[ tid ] = tcase

        if tcase:
            copy_test_results( tcase, tmp_tcase )
            self.tlist.appendTestResult( tcase )

        return tcase

    def _pop_next_test(self, platform=None):
        ""
        if platform == None:
            def testok( tcase ):
                return tcase.getBlockingDependency() == None
            tcase = self.backlog.pop( constraint=testok )
        else:
            avail = platform.maxAvailableSize()
            def testok( tcase ):
                np = tcase.getSpec().getParameters().get('np',0)
                npval = max( int(np), 1 )
                block = tcase.getBlockingDependency()
                return npval <= avail and block == None
            # magic: send avail down into pop for efficiency
            #        - in fact, using max_size means the testok() function
            #          is not needed
            tcase = self.backlog.pop( constraint=testok )

        if tcase != None:
            self.waiting[ tcase.getSpec().getID() ] = tcase

        return tcase


class TestBacklog:
    """
    be able to iterate by largest np first then largest runtime/timeout
    be able to pop a test that fits the criteria

    advantage of storing by np is that in a search for a test that will
    fit, all tests with a larger np can be skipped right over

    but how would that work with (np,ndevice) ??
        - maybe skip np but have to iterate for ndevice

    needs:
        - iterate the list, determine if the test can be accepted, if so then
          pop it off the backlog and place into 'waiting'
        - the order of iteration matters for efficiency
            - batch prefers alignment with size (with timeout secondary)
            - pooled prefers large runtimes first (with constraint on size)
    """

    def __init__(self):
        ""
        self.tests = []
        self.testcmp = None

    def insert(self, tcase):
        """
        Note: to support streaming, this function would have to use
              self.testcmp to do an insert (rather than an append)
        """
        self.tests.append( tcase )

    def sort(self, secondary='runtime'):
        ""
        if secondary == 'runtime':
            self.testcmp = TestCaseCompare( make_runtime_key )
        else:
            self.testcmp = TestCaseCompare( make_timeout_key )

        if sys.version_info[0] < 3:
            self.tests.sort( self.testcmp.compare, reverse=True )
        else:
            self.tests.sort( key=self.testcmp.getKey, reverse=True )

    def getStartingIndex(self, max_size=None):
        ""
        return 0

    def pop(self, max_size=None, constraint=None):
        ""
        tcase = None

        idx = self.getStartingIndex( max_size )
        while idx < len( self.tests ):
            if constraint == None or constraint( self.tests[idx] ):
                tcase = self.tests.pop( idx )
                break
            idx += 1

        return tcase

    def consume(self):
        ""
        while len( self.tests ) > 0:
            tcase = self.tests.pop( 0 )
            yield tcase

    def iterate(self):
        ""
        for tcase in self.tests:
            yield tcase


def make_runtime_key( tcase ):
    ""
    return [ int( tcase.getSpec().getParameters().get( 'np', 0 ) ),
             tcase.getStat().getRuntime( 0 ) ]

def make_timeout_key( tcase ):
    ""
    ts = tcase.getSpec()
    return [ int( ts.getParameters().get( 'np', 0 ) ),
             ts.getAttr( 'timeout' ) ]


class TestCaseCompare:

    def __init__(self, make_key):
        ""
        self.kfunc = make_key

    def compare(self, x, y):
        ""
        k1 = self.kfunc(x)
        k2 = self.kfunc(y)
        if k1 < k2: return -1
        if k2 < k1: return 1
        return 0

    def getKey(self, x):
        ""
        return self.kfunc( x )






def bisect_right( a, x, less_than ):
    ""
    lo = 0
    hi = len(a)
    while lo < hi:
        mid = (lo+hi)//2
        if less_than( x, a[mid] ): hi = mid
        else: lo = mid+1
    return lo


def less_than_using_np_and_runtime( x, y ):
    ""
    return [ int( x.getSpec().getParameters().get( 'np', 0 ) ),
             x.getStat().getRuntime( 0 ) ] \
           < \
           [ int( y.getSpec().getParameters().get( 'np', 0 ) ),
             y.getStat().getRuntime( 0 ) ]


def less_than_using_np_and_timeout( x, y ):
    ""
    tspec1 = x.getSpec()
    tspec2 = y.getSpec()
    return [ int( tspec1.getParameters().get( 'np', 0 ) ),
             tspec1.getAttr( 'timeout' ) ] \
           < \
           [ int( tspec2.getParameters().get( 'np', 0 ) ),
             tspec2.getAttr( 'timeout' ) ]


def insort_right( a, x, less_than ):
    ""
    lo = 0
    hi = len(a)
    while lo < hi:
        mid = (lo+hi)//2
        if less_than( x, a[mid] ): hi = mid
        else: lo = mid+1
    a.insert(lo, x)
