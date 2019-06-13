#!/usr/bin/env python

# Copyright 2018 National Technology & Engineering Solutions of Sandia, LLC
# (NTESS). Under the terms of Contract DE-NA0003525 with NTESS, the U.S.
# Government retains certain rights in this software.

import os, sys
import time
import glob

from .TestSpecError import TestSpecError
from . import TestSpec
from .testcase import TestCase
from . import testlistio
from .groups import ParameterizeAnalyzeGroups


class TestList:
    """
    Stores a set of TestCase objects.  Has utilities to read/write to a text
    file and to read from a test XML file.
    """

    def __init__(self, statushandler, filename,
                       runtime_config=None,
                       testcreator=None,
                       testfilter=None):
        ""
        self.statushandler = statushandler

        if filename:
            self.filename = os.path.normpath( filename )
        else:
            # use case: scanning tests, but never reading or writing
            self.filename = None

        self.results_suffix = None
        self.results_file = None

        self.datestamp = None
        self.finish = None

        self.groups = None  # a ParameterizeAnalyzeGroups class instance

        self.tcasemap = {}  # TestSpec xdir -> TestCase object

        self.rtconfig = runtime_config
        self.creator = testcreator
        self.testfilter = testfilter

    def setResultsSuffix(self, suffix=None):
        ""
        if suffix:
            self.results_suffix = suffix
        elif not self.results_suffix:
            self.results_suffix = time.strftime( "%Y-%m-%d_%H:%M:%S" )

        return self.results_suffix

    def getResultsSuffix(self):
        ""
        return self.results_suffix

    def stringFileWrite(self, include_results_suffix=False):
        """
        Writes all the tests in this container to the test list file.  If
        'include_results_suffix' is True, the results suffix is written as
        an attribute in the file.
        """
        assert self.filename

        check_make_directory_containing_file( self.filename )

        tlw = testlistio.TestListWriter( self.filename )

        if include_results_suffix:
            assert self.results_suffix
            tlw.start( results_suffix=self.results_suffix )
        else:
            tlw.start()

        for tcase in self.tcasemap.values():
            tlw.append( tcase )

        tlw.finish()

    def initializeResultsFile(self):
        ""
        self.setResultsSuffix()

        rfile = self.filename + '.' + self.results_suffix
        
        self.results_file = testlistio.TestListWriter( rfile )

        self.results_file.start()

        return rfile

    def addIncludeFile(self, testlist_path):
        """
        Appends the given filename to the test results file.
        """
        assert self.results_suffix, 'suffix must have already been set'
        inclf = testlist_path + '.' + self.results_suffix
        self.results_file.addIncludeFile( inclf )

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

            self.results_suffix = tlr.getAttr( 'results_suffix', None )

            for xdir,tcase in tlr.getTests().items():
                if xdir not in self.tcasemap:
                    self.tcasemap[ xdir ] = tcase

    def readTestResults(self, resultsfilename=None):
        ""
        if resultsfilename == None:
            self._read_file_list( self.getResultsFilenames() )
        else:
            self._read_file_list( [ resultsfilename ] )

    def getResultsFilenames(self):
        ""
        assert self.filename
        fileL = glob.glob( self.filename+'.*' )
        fileL.sort()
        return fileL

    def _read_file_list(self, files):
        ""
        for fn in files:

            tlr = testlistio.TestListReader( fn )
            tlr.read()

            self.datestamp = tlr.getStartDate()
            self.finish = tlr.getFinishDate()

            for xdir,tcase in tlr.getTests().items():

                t = self.tcasemap.get( xdir, None )
                if t != None:
                    self.statushandler.copyResults( t, tcase )

    def ensureInlinedTestResultIncludes(self):
        ""
        fL = self.getResultsFilenames()
        if len(fL) > 0:
            # only the most recent is checked
            testlistio.inline_include_files( fL[-1] )

    def inlineIncludeFiles(self):
        ""
        rfile = self.filename + '.' + self.results_suffix
        testlistio.inline_include_files( rfile )

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
        Returns a map of xdir to TestCase containing all tests.
        """
        return self.tcasemap

    def getGroupMap(self):
        ""
        return self.groups

    def applyPermanentFilters(self):
        ""
        self._check_create_parameterize_analyze_group_map()

        self.testfilter.applyPermanent( self.tcasemap )

        finalize_analyze_tests( self.statushandler, self.groups )

        self.numactive = count_active( self.statushandler, self.tcasemap )

    def determineActiveTests(self, filter_dir=None,
                                   analyze_only=False,
                                   baseline=False):
        ""
        self._check_create_parameterize_analyze_group_map()

        self.testfilter.applyRuntime( self.tcasemap, filter_dir )

        if not baseline:
            finalize_analyze_tests( self.statushandler, self.groups )

        refresh_active_tests( self.statushandler, self.tcasemap, self.creator )

        if baseline:
            # baseline marking must come after TestSpecs are refreshed
            mark_skips_for_baselining( self.statushandler, self.tcasemap )

        self.numactive = count_active( self.statushandler, self.tcasemap )

    def numActive(self):
        """
        Return the total number of active tests (the tests that are to be run).
        """
        return self.numactive

    def getActiveTests(self, sorting=''):
        """
        Get a list of the active tests (after filtering).  If 'sorting' is
        not an empty string, it should be a set of characters that control the
        way the test sorting is performed.
                n : test name (the default)
                x : execution directory name
                t : test run time
                d : execution date
                s : test status (such as pass, fail, diff, etc)
                r : reverse the order
        """
        if not sorting:
            sorting = 'nx'

        tL = []

        for tcase in self.tcasemap.values():
            t = tcase.getSpec()
            if not self.statushandler.skipTest(t):
                subL = []
                for c in sorting:
                    if c == 'n':
                        subL.append( t.getName() )
                    elif c == 'x':
                        subL.append( t.getExecuteDirectory() )
                    elif c == 't':
                        tm = self.statushandler.getRuntime( t, None )
                        if tm == None: tm = 0
                        subL.append( tm )
                    elif c == 'd':
                        subL.append( self.statushandler.getStartDate( t, 0 ) )
                    elif c == 's':
                        subL.append( self.statushandler.getResultStatus( t ) )

                subL.append( tcase )
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
            tspec = tcase.getSpec()
            if not self.statushandler.skipTest( tspec ):
                result = self.statushandler.getResultStatus( tspec )
                if   result == 'diff'   : ival |= ( 2**1 )
                elif result == 'fail'   : ival |= ( 2**2 )
                elif result == 'timeout': ival |= ( 2**3 )
                elif result == 'notdone': ival |= ( 2**4 )
                elif result == 'notrun' : ival |= ( 2**5 )
        return ival

    def scanDirectory(self, base_directory, force_params=None):
        """
        Recursively scans for test XML or VVT files starting at 'base_directory'.
        If 'force_params' is not None, it must be a dictionary mapping
        parameter names to a list of parameter values.  Any test that contains
        a parameter in this dictionary will take on the given values for that
        parameter.
        """
        bdir = os.path.normpath( os.path.abspath(base_directory) )
        for root,dirs,files in os.walk( bdir ):
            self._scan_recurse( bdir, force_params, root, dirs, files )

    def _scan_recurse(self, basedir, force_params, d, dirs, files):
        """
        This function is given to os.walk to recursively scan a directory
        tree for test XML files.  The 'basedir' is the directory originally
        sent to the os.walk function.
        """
        d = os.path.normpath(d)

        if basedir == d:
            reldir = '.'
        else:
            assert basedir+os.sep == d[:len(basedir)+1]
            reldir = d[len(basedir)+1:]

        # scan files with extension "xml" or "vvt"; soft links to directories
        # are skipped by os.walk so special handling is performed

        for f in files:
            bn,ext = os.path.splitext(f)
            df = os.path.join(d,f)
            if bn and ext in ['.xml','.vvt']:
                self.readTestFile( basedir, os.path.join(reldir,f), force_params )

        linkdirs = []
        for subd in list(dirs):
            rd = os.path.join( d, subd )
            if not os.path.exists(rd) or \
                    subd.startswith("TestResults.") or \
                    subd.startswith("Build_"):
                dirs.remove( subd )
            elif os.path.islink(rd):
                linkdirs.append( rd )

        # TODO: should check that the soft linked directories do not
        #       point to a parent directory of any of the directories
        #       visited thus far (to avoid an infinite scan loop)
        #       - would have to use os.path.realpath() or something because
        #         the actual path may be the softlinked path rather than the
        #         path obtained by following '..' all the way to root

        # manually recurse into soft linked directories
        for ld in linkdirs:
            for lroot,ldirs,lfiles in os.walk( ld ):
                self._scan_recurse( basedir, force_params, lroot, ldirs, lfiles )
    
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
            # this new test is ignored if it was already read from source
            # (or a different test source but the same relative path from root)
            xdir = tspec.getExecuteDirectory()

            if xdir in self.tcasemap:
                tcase = self.tcasemap[ xdir ]
                tspec1 = tcase.getSpec()
                print3( '*** warning:',
                    'ignoring test with duplicate execution directory\n',
                    '      first file :', tspec1.getFilename() + '\n',
                    '      second file:', tspec.getFilename() )
            else:
                self.tcasemap[xdir] = TestCase( tspec )

    def addTest(self, tcase):
        """
        Add/overwrite a test in the list.
        """
        self.tcasemap[ tcase.getSpec().getExecuteDirectory() ] = tcase

    def _check_create_parameterize_analyze_group_map(self):
        ""
        if self.groups == None:
            self.groups = ParameterizeAnalyzeGroups( self.statushandler )
            self.groups.rebuild( self.tcasemap )


def check_make_directory_containing_file( filename ):
    ""
    d,b = os.path.split( filename )
    if d and d != '.':
        if not os.path.exists(d):
            os.mkdir( d )


def mark_skips_for_baselining( statushandler, tcase_map ):
    ""
    for xdir,tcase in tcase_map.items():
        tspec = tcase.getSpec()
        if not statushandler.skipTest( tspec ):
            if not tspec.hasBaseline():
                statushandler.markSkipByBaselineHandling( tspec )


def finalize_analyze_tests( statushandler, groups ):
    ""
    for analyze, tcaseL in groups.iterateGroups():

        skip_analyze = False
        paramsets = []

        for tcase in tcaseL:
            if statushandler.skipTestCausingAnalyzeSkip( tcase.getSpec() ):
                skip_analyze = True
            else:
                paramsets.append( tcase.getSpec().getParameters() )

        if skip_analyze:
            if not statushandler.skipTest( analyze.getSpec() ):
                statushandler.markSkipByAnalyzeDependency( analyze.getSpec() )
        else:
            def evalfunc( paramD ):
                for D in paramsets:
                    if paramD == D:
                        return True
                return False
            pset = analyze.getSpec().getParameterSet()
            pset.applyParamFilter( evalfunc )


def count_active( statushandler, tcase_map ):
    ""
    cnt = 0
    for tcase in tcase_map.values():
        if not statushandler.skipTest( tcase.getSpec() ):
            cnt += 1
    return cnt


def refresh_active_tests( statushandler, tcase_map, creator ):
    ""
    for xdir,tcase in tcase_map.items():
        tspec = tcase.getSpec()
        if not statushandler.skipTest( tspec ):
            if not tspec.constructionCompleted():
                creator.reparse( tspec )


###########################################################################

def print3( *args ):
    sys.stdout.write( ' '.join( [ str(arg) for arg in args ] ) + '\n' )
    sys.stdout.flush()
