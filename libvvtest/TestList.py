#!/usr/bin/env python

# Copyright 2018 National Technology & Engineering Solutions of Sandia, LLC
# (NTESS). Under the terms of Contract DE-NA0003525 with NTESS, the U.S.
# Government retains certain rights in this software.

import os, sys
import time
import glob
from os.path import abspath, normpath
from os.path import join as pjoin

from . import testlistio
from .groups import ParameterizeAnalyzeGroups
from .teststatus import copy_test_results
from .testctor import TestConstructor


default_filename = 'testlist'


class TestList:
    """
    Stores a set of TestCase objects and has utilities to read and write them
    to a file.
    """

    def __init__(self, filename=None, testctor=None):
        ""
        if filename:
            self.filename = normpath( abspath( filename ) )
        else:
            self.filename = abspath( default_filename )

        self.tctor = testctor

        self.rundate = None
        self.results_file = None

        # magic: make these two attributes
        self.datestamp = None
        self.finish = None

        self.groups = None  # a ParameterizeAnalyzeGroups class instance

        self.tcasemap = {}  # TestSpec ID -> TestCase object

    def getFilename(self):
        ""
        return self.filename

    def setResultsSuffix(self, suffix=None):
        ""
        # magic: make this an attribute called 'rundate'
        #        and move the default date formatter out of this class
        #        or pass the time in seconds (for consistency)
        #   - and rename this function setResultsDate()
        if suffix:
            self.rundate = suffix
        elif not self.rundate:
            self.rundate = time.strftime( "%Y-%m-%d_%H:%M:%S" )

        return self.rundate

    def getResultsFilename(self):
        ""
        return self.filename+'.'+self.rundate

    def getResultsSuffix(self):
        ""
        return self.rundate

    def stringFileWrite(self, extended=False, **file_attrs):
        """
        Writes all the tests in this container to the test list file.  If
        'extended' is True, additional information is written to make the
        file more self-contained.
        """
        assert self.filename

        tlw = testlistio.TestListWriter( self.filename )

        if extended:
            tlw.start( rundate=self.rundate, **file_attrs )
        else:
            tlw.start( **file_attrs)

        for tcase in self.tcasemap.values():
            tlw.append( tcase, extended=extended )

        tlw.finish()

        return self.filename

    def initializeResultsFile(self, **file_attrs):
        ""
        self.setResultsSuffix()

        rfile = self.filename + '.' + self.rundate
        
        self.results_file = testlistio.TestListWriter( rfile )

        self.results_file.start( **file_attrs )

        return rfile

    def addIncludeFile(self, testlist_path):
        """
        Appends the given filename to the test results file.
        """
        assert self.rundate, 'suffix must have already been set'
        inclf = testlist_path + '.' + self.rundate
        self.results_file.addIncludeFile( inclf )

    def completeIncludeFile(self, testlist_path):
        ""
        assert self.rundate, 'suffix must have already been set'
        inclf = testlist_path + '.' + self.rundate
        self.results_file.includeFileCompleted( inclf )

    def appendTestResult(self, tcase):
        """
        Appends the results file with the name and attributes of the given
        TestCase object.
        """
        self.results_file.append( tcase )

    def writeFinished(self):
        """
        Appends the results file with a finish marker that contains the
        current date.
        """
        self.results_file.finish()

    def readTestList(self):
        ""
        assert self.filename

        if os.path.exists( self.filename ):

            tlr = testlistio.TestListReader( self.filename )
            tlr.read( self.tctor )

            self.rundate = tlr.getAttr( 'rundate', None )

            for xdir,tcase in tlr.getTests().items():
                if xdir not in self.tcasemap:
                    self.tcasemap[ xdir ] = tcase

    def readTestResults(self, preserve_skips=False):
        """
        Glob for results filenames and read them all in increasing order
        by rundate.

        If 'preserve_skips' is False, each test read in from a results file
        will have its skip setting removed from the test.
        """
        fL = glob_results_files( self.filename )
        file_attrs = self._read_file_list( fL, preserve_skips )
        return file_attrs

    def resultsFileIsMarkedFinished(self):
        ""
        finished = True

        rfileL = glob_results_files( self.filename )
        if len(rfileL) > 0:
           if not testlistio.file_is_marked_finished( rfileL[-1] ):
                finished = False

        return finished

    def _read_file_list(self, files, preserve_skips):
        ""
        file_attrs = {}

        for fn in files:

            tlr = testlistio.TestListReader( fn )
            tlr.read( self.tctor )

            self.datestamp = tlr.getStartDate()
            self.finish = tlr.getFinishDate()

            file_attrs.clear()
            file_attrs.update( tlr.getAttrs() )
            if self.finish:
                file_attrs['finishepoch'] = self.finish

            tctor = make_TestConstructor( file_attrs )

            for xdir,tcase in tlr.getTests().items():

                t = self.tcasemap.get( xdir, None )
                if t != None:
                    tctor.resetTestID( t.getSpec() )
                    copy_test_results( t, tcase )
                    if not preserve_skips:
                        t.getStat().removeAttr( 'skip' )

        return file_attrs

    def getDateStamp(self, default=None):
        """
        Return the start date from the last test results file read using the
        readTestResults() function.  If a read has not been done, the 'default'
        argument is returned.
        """
        if self.datestamp:
            return self.datestamp
        return default

    def getFinishDate(self, default=None):
        """
        Return the finish date from the last test results file read using the
        readTestResults() function.  If a read has not been done, or vvtest is
        still running, or vvtest got killed in the middle of running, the
        'default' argument is returned.
        """
        if self.finish:
            return self.finish
        return default

    def getTests(self):
        """
        Returns, in a list, all tests either scanned or read from a file.
        """
        return self.tcasemap.values()

    def getTestMap(self):
        """
        Returns all tests as a map from test ID to TestCase.
        """
        return self.tcasemap

    def getGroupMap(self):
        ""
        return self.groups

    def countActive(self):
        ""
        cnt = 0
        for tcase in self.tcasemap.values():
            if not tcase.getStat().skipTest():
                cnt += 1
        self.numactive = cnt

    def numActive(self):
        """
        Return the total number of active tests (the tests to be run).
        """
        return self.numactive

    def getActiveTests(self, sorting=''):
        """
        Get a list of the active tests (after filtering).  If 'sorting' is
        not an empty string, it should be a set of characters that control the
        way the test sorting is performed.
                n : test name
                x : execution directory name (the default)
                t : test run time
                d : execution date
                s : test status (such as pass, fail, diff, etc)
                r : reverse the order
        """
        if not sorting:
            sorting = 'xd'

        tL = []

        for idx,tcase in enumerate( self.tcasemap.values() ):
            t = tcase.getSpec()
            if not tcase.getStat().skipTest():
                subL = []
                for c in sorting:
                    if c == 'n':
                        subL.append( t.getName() )
                    elif c == 'x':
                        subL.append( t.getDisplayString() )
                    elif c == 't':
                        tm = tcase.getStat().getRuntime( None )
                        if tm == None: tm = 0
                        subL.append( tm )
                    elif c == 'd':
                        subL.append( tcase.getStat().getStartDate( 0 ) )
                    elif c == 's':
                        subL.append( tcase.getStat().getResultStatus() )

                subL.extend( [ idx, tcase ] )
                tL.append( subL )
        tL.sort()
        if 'r' in sorting:
            tL.reverse()
        tL = [ L[-1] for L in tL ]

        return tL

    def encodeIntegerWarning(self):
        ""
        # magic: move this encoding logic out of this class
        ival = 0
        for tcase in self.tcasemap.values():
            if not tcase.getStat().skipTest():
                result = tcase.getStat().getResultStatus()
                if   result == 'diff'   : ival |= ( 2**1 )
                elif result == 'fail'   : ival |= ( 2**2 )
                elif result == 'timeout': ival |= ( 2**3 )
                elif result == 'notdone': ival |= ( 2**4 )
                elif result == 'notrun' : ival |= ( 2**5 )
        return ival

    def addTest(self, tcase):
        """
        Add/overwrite a test in the list.
        """
        self.tcasemap[ tcase.getSpec().getID() ] = tcase

    def createAnalyzeGroupMap(self):
        ""
        if self.groups == None:
            self.groups = ParameterizeAnalyzeGroups()
            self.groups.rebuild( self.tcasemap )

        return self.groups


def glob_results_files( basename ):
    ""
    assert basename
    fileL = glob.glob( basename+'.*' )
    fileL.sort()
    return fileL


def make_TestConstructor( file_attrs ):
    ""
    tctor = TestConstructor()

    nc = file_attrs.get( 'shortxdirs', None )
    if nc != None:
        tctor.setShorten( int(nc) )

    return tctor
