#!/usr/bin/env python

# Copyright 2018 National Technology & Engineering Solutions of Sandia, LLC
# (NTESS). Under the terms of Contract DE-NA0003525 with NTESS, the U.S.
# Government retains certain rights in this software.

import os, sys
import time
import glob
from os.path import abspath, normpath
from os.path import join as pjoin

from .errors import TestSpecError
from .testcase import TestCase
from . import testlistio
from .groups import ParameterizeAnalyzeGroups
from .teststatus import copy_test_results


class TestList:
    """
    Stores a set of TestCase objects and has utilities to read and write them
    to a file.
    """

    base_filename = 'testlist'

    def __init__(self, directory=None,
                       identifier=None,
                       runtime_config=None,
                       testcreator=None,
                       testfilter=None):
        ""
        if not directory:
            directory = os.getcwd()

        fn = pjoin( directory, TestList.base_filename )
        self.filename = normpath( abspath( fn ) )

        if identifier != None:
            self.filename += '.'+str(identifier)

        self.rundate = None
        self.results_file = None

        self.datestamp = None
        self.finish = None

        self.groups = None  # a ParameterizeAnalyzeGroups class instance

        self.xdirmap = {}  # TestSpec xdir -> TestCase object
        self.tcasemap = {}  # TestSpec ID -> TestCase object

        self.rtconfig = runtime_config
        self.creator = testcreator
        self.testfilter = testfilter

    def getFilename(self):
        ""
        return self.filename

    def setResultsSuffix(self, suffix=None):
        ""
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

    def stringFileWrite(self, extended=False):
        """
        Writes all the tests in this container to the test list file.  If
        'extended' is True, additional information is written to make the
        file more self-contained.
        """
        assert self.filename

        tlw = testlistio.TestListWriter( self.filename )

        if extended:
            tlw.start( rundate=self.rundate )
        else:
            tlw.start()

        for tcase in self.tcasemap.values():
            tlw.append( tcase, extended=extended )

        tlw.finish()

        return self.filename

    def initializeResultsFile(self):
        ""
        self.setResultsSuffix()

        rfile = self.filename + '.' + self.rundate
        
        self.results_file = testlistio.TestListWriter( rfile )

        self.results_file.start()

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
            tlr.read()

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
        self._read_file_list( fL, preserve_skips )

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
        for fn in files:

            tlr = testlistio.TestListReader( fn )
            tlr.read()

            self.datestamp = tlr.getStartDate()
            self.finish = tlr.getFinishDate()

            for xdir,tcase in tlr.getTests().items():

                t = self.tcasemap.get( xdir, None )
                if t != None:
                    copy_test_results( t, tcase )
                    if not preserve_skips:
                        t.getSpec().attrs.pop( 'skip', None )

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

    def applyPermanentFilters(self):
        ""
        self._check_create_parameterize_analyze_group_map()

        self.testfilter.applyPermanent( self.tcasemap )

        for analyze, tcaseL in self.groups.iterateGroups():
            self.testfilter.checkAnalyze( analyze, tcaseL )

        self.numactive = count_active( self.tcasemap )

    def determineActiveTests(self, filter_dir=None,
                                   baseline=False,
                                   apply_filters=True,
                                   remove_skips=False):
        """
        If 'remove_skips' is True then every test skipped by the current
        filtering is removed entirely from the test list.
        """
        self._check_create_parameterize_analyze_group_map()

        if apply_filters:
            self.testfilter.applyRuntime( self.tcasemap, filter_dir,
                                          force_checks=remove_skips )

            for analyze, tcaseL in self.groups.iterateGroups():
                self.testfilter.checkAnalyze( analyze, tcaseL )

            if remove_skips:
                self.testfilter.removeNewSkips( self.tcasemap )

        refresh_active_tests( self.tcasemap, self.creator )

        if baseline:
            # baseline marking must come after TestSpecs are refreshed
            self.testfilter.applyBaselineSkips( self.tcasemap )

        self.numactive = count_active( self.tcasemap )

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

    def readTestFile(self, basepath, relfile, force_params):
        """
        Initiates the parsing of a test file.  XML test descriptions may be
        skipped if they don't appear to be a test file.  Attributes from
        existing tests will be absorbed.
        """
        assert basepath
        assert relfile
        assert os.path.isabs( basepath )
        assert not os.path.isabs( relfile )

        basepath = os.path.normpath( basepath )
        relfile  = os.path.normpath( relfile )

        assert relfile

        try:
            testL = self.creator.fromFile( basepath, relfile, force_params )
        except TestSpecError:
          print3( "*** skipping file " + os.path.join( basepath, relfile ) + \
                  ": " + str( sys.exc_info()[1] ) )
          testL = []

        for tspec in testL:
            if not self._is_duplicate_execute_directory( tspec ):
                testid = tspec.getID()
                tcase = TestCase( tspec )
                self.tcasemap[testid] = tcase
                self.xdirmap[ tspec.getExecuteDirectory() ] = tcase

    def addTest(self, tcase):
        """
        Add/overwrite a test in the list.
        """
        self.tcasemap[ tcase.getSpec().getID() ] = tcase

    def _check_create_parameterize_analyze_group_map(self):
        ""
        if self.groups == None:
            self.groups = ParameterizeAnalyzeGroups()
            self.groups.rebuild( self.tcasemap )

    def _is_duplicate_execute_directory(self, tspec):
        ""
        xdir = tspec.getExecuteDirectory()

        tcase0 = self.xdirmap.get( xdir, None )

        if tcase0 != None and \
           not tests_are_related_by_staging( tcase0.getSpec(), tspec ):

            tspec0 = tcase0.getSpec()

            print3( '*** warning:',
                'ignoring test with duplicate execution directory\n',
                '      first   :', tspec0.getFilename() + '\n',
                '      second  :', tspec.getFilename() + '\n',
                '      exec dir:', xdir )

            ddir = tspec.getDisplayString()
            if ddir != xdir:
                print3( '       test id :', ddir )

            return True

        return False


def tests_are_related_by_staging( tspec1, tspec2 ):
    ""
    xdir1 = tspec1.getExecuteDirectory()
    disp1 = tspec1.getDisplayString()

    xdir2 = tspec2.getExecuteDirectory()
    disp2 = tspec2.getDisplayString()

    if xdir1 == xdir2 and \
       tspec1.getFilename() == tspec2.getFilename() and \
       xdir1 != disp1 and disp1.startswith( xdir1 ) and \
       xdir2 != disp2 and disp2.startswith( xdir2 ):
        return True

    return False


def count_active( tcase_map ):
    ""
    cnt = 0
    for tcase in tcase_map.values():
        if not tcase.getStat().skipTest():
            cnt += 1
    return cnt


def refresh_active_tests( tcase_map, creator ):
    ""
    for xdir,tcase in tcase_map.items():
        tspec = tcase.getSpec()
        if not tcase.getStat().skipTest():
            if not tspec.constructionCompleted():
                creator.reparse( tspec )


def glob_results_files( basename ):
    ""
    assert basename
    fileL = glob.glob( basename+'.*' )
    fileL.sort()
    return fileL


###########################################################################

def print3( *args ):
    sys.stdout.write( ' '.join( [ str(arg) for arg in args ] ) + '\n' )
    sys.stdout.flush()
