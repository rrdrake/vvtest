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

        self.backlog = {}  # np -> list of TestCase objects
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

        for tcase in self.getTestExecList():
            self.runner.initialize_for_execution( tcase )

    def _generate_backlog_from_testlist(self):
        ""
        self.backlog = {}

        for tcase in self.tlist.getTests():

            tspec = tcase.getSpec()

            if not tcase.getStat().skipTest():

                assert tspec.constructionCompleted()

                tcase.setExec( TestExec() )

                np = int( tspec.getParameters().get('np', 0) )
                if np in self.backlog:
                    self.backlog[np].append( tcase )
                else:
                    self.backlog[np] = [ tcase ]

    def _connect_execute_dependencies(self):
        ""
        tmap = self.tlist.getTestMap()
        groups = self.tlist.getGroupMap()

        for tcase in self.getTestExecList():

            tspec = tcase.getSpec()

            if tspec.isAnalyze():
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
        for np,tcaseL in self.backlog.items():
            sortL = []
            for tcase in tcaseL:
                tm = tcase.getStat().getRuntime( None )
                if tm == None: tm = 0
                xdir = tcase.getSpec().getDisplayString()
                sortL.append( (tm,xdir,tcase) )
            sortL.sort( reverse=True )
            tcaseL[:] = [ tcase for tm,xdir,tcase in sortL ]

    def sortBySizeAndTimeout(self):
        ""
        self.sortlist = []

        for np in self.backlog.keys():
            for tcase in self.backlog[np]:
                tm = tcase.getSpec().getAttr( 'timeout' )
                xdir = tcase.getSpec().getDisplayString()
                self.sortlist.append( (np,tm,xdir,tcase) )

        self.sortlist.sort()

    def getNextTest(self):
        ""
        # magic: goal here is to store the backlog in a class that can
        #        do the sorting and pop-ing efficiently
        if len( self.sortlist ) > 0:
            np,tm,xdir,tcase = self.sortlist.pop()
            for i in range( len(self.backlog[np]) ):
                # magic: use getID() instead (also above)
                if xdir == self.backlog[np][i].getSpec().getDisplayString():
                    self._pop_test_exec( np, i )
                    return tcase
        return None


    def getTestExecProcList(self):  # magic: remove
        """
        Returns a list of integers; each integer is the number of processors
        needed by one or more tests in the TestExec list.
        """
        return self.backlog.keys()

    def getTestExecList(self, numprocs=None, consume=False):
        """
        If 'numprocs' is None, all TestExec objects are returned.  If 'numprocs'
        is not None, a list of TestExec objects is returned each of which need
        that number of processors to run.

        If 'consume' is True, the tests are moved from backlog to waiting.
        """
        # magic: remove the numprocs and consume arguments
        xL = []

        for np,tcaseL in list( self.backlog.items() ):
            if numprocs == None:
                xL.extend( tcaseL )
                if consume:
                    self._consume_tests( np )
            elif numprocs == np:
                xL.extend( tcaseL )
                if consume:
                    self._consume_tests( np )
                break

        return xL

    def popNext(self, platform):
        """
        Finds a test to execute.  Returns a TestExec object, or None if no
        test can run.  In this case, one of the following is true

            1. there are not enough free processors to run another test
            2. the only tests left have a dependency with a bad result (like
               a fail) preventing the test from running

        In the latter case, numRunning() will be zero.
        """
        npL = list( self.backlog.keys() )
        npL.sort()
        npL.reverse()

        # find longest runtime test such that the num procs is available
        tcase = self._pop_next_test( npL, platform )
        if tcase == None and len(self.started) == 0:
            # search for tests that need more processors than platform has
            tcase = self._pop_next_test( npL )

        return tcase

    def consumeBacklog(self):
        ""
        for np,tcaseL in list( self.backlog.items() ):
            while len( tcaseL ) > 0:
                tcase = tcaseL[0]
                self._pop_test_exec( np, 0 )
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
        tL = []
        for np,tcaseL in list( self.backlog.items() ):
            tL.extend( tcaseL )
            del tcaseL[:]
            self.backlog.pop( np )
        return tL

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

    def _consume_tests(self, np):
        ""
        tcaseL = self.backlog[np]
        while len( tcaseL ) > 0:
            self._pop_test_exec( np, 0 )

    def _pop_next_test(self, npL, platform=None):
        ""
        # magic: instead of query procs with np, ask for available np
        for np in npL:
            if platform == None or platform.queryProcs(np):
                tcaseL = self.backlog[np]
                N = len(tcaseL)
                i = 0
                while i < N:
                    tcase = tcaseL[i]
                    if tcase.getBlockingDependency() == None:
                        self._pop_test_exec( np, i )
                        return tcase
                    i += 1
        return None

    def _pop_test_exec(self, np, i):
        ""
        tcaseL = self.backlog[np]
        tcase = tcaseL[i]

        del tcaseL[i]

        self.waiting[ tcase.getSpec().getID() ] = tcase

        if len(tcaseL) == 0:
            self.backlog.pop( np )
