#!/usr/bin/env python

# Copyright 2018 National Technology & Engineering Solutions of Sandia, LLC
# (NTESS). Under the terms of Contract DE-NA0003525 with NTESS, the U.S.
# Government retains certain rights in this software.

import os, sys
import time
from os.path import join as pjoin

from . import outpututils


class HTMLWriter:

    def __init__(self, statushandler, permsetter,
                       output_filename, results_test_dir):
        ""
        self.statushandler = statushandler
        self.permsetter = permsetter
        self.filename = os.path.normpath( os.path.abspath( output_filename ) )
        self.testdir = results_test_dir

    def writeDocument(self, tlist):
        """
        Opens and writes an HTML summary file in the test directory.
        """
        datestamp = tlist.getDateStamp( time.time() )
        datestr = outpututils.make_date_stamp( datestamp, None,
                                               "%Y-%m-%d %H:%M:%S" )

        parts = outpututils.partition_tests_by_result( self.statushandler,
                                                       tlist.getActiveTests() )

        sumstr = outpututils.results_summary_string( parts )

        fp = open( self.filename, "w" )
        try:
            fp.write( "<html>\n<head>\n<title>Test Results</title>\n" )
            fp.write( "</head>\n<body>\n" )

            # a summary section

            fp.write( "<h1>Summary</h1>\n" )
            fp.write( "  <ul>\n" )
            fp.write( "  <li> Test date: " + datestr + " </li>\n" )
            fp.write( "  <li> Directory: " + self.testdir + " </li>\n" )
            fp.write( "  <li> " + sumstr + "</li>\n" )
            fp.write( "  </ul>\n" )

            # segregate the tests into implicit keywords, such as fail and diff

            fp.write( '<h1>Tests that showed "fail"</h1>\n' )
            self.writeTestList( fp, parts['fail'] )
            fp.write( '<h1>Tests that showed "timeout"</h1>\n' )
            self.writeTestList( fp, parts['timeout'] )
            fp.write( '<h1>Tests that showed "diff"</h1>\n' )
            self.writeTestList( fp, parts['diff'] )
            fp.write( '<h1>Tests that showed "notdone"</h1>\n' )
            self.writeTestList( fp, parts['notdone'] )
            fp.write( '<h1>Tests that showed "pass"</h1>\n' )
            self.writeTestList( fp, parts['pass'] )
            fp.write( '<h1>Tests that showed "notrun"</h1>\n' )
            self.writeTestList( fp, parts['notrun'] )

            fp.write( "</body>\n</html>\n" )

        finally:
            fp.close()
            self.permsetter.set( os.path.abspath( self.filename ) )

    def writeTestList(self, fp, tlist):
        """
        Used by printHTMLResults().  Writes the HTML for a list of tests to the
        HTML summary file.
        """
        cwd = os.getcwd()

        fp.write( '  <ul>\n' )

        for atest in tlist:

            xs = outpututils.XstatusString( self.statushandler,
                                            atest, self.testdir, cwd )
            fp.write( '  <li><code>' + xs + '</code>\n' )

            ref = outpututils.ensure_TestSpec( atest )

            tdir = pjoin( self.testdir, ref.getExecuteDirectory() )
            assert cwd == tdir[:len(cwd)]
            reltdir = tdir[len(cwd)+1:]

            fp.write( "<ul>\n" )
            thome = atest.getRootpath()
            xfile = pjoin( thome, atest.getFilepath() )
            fp.write( '  <li>XML: <a href="file://' + xfile + '" ' + \
                             'type="text/plain">' + xfile + "</a></li>\n" )
            fp.write( '  <li>Parameters:<code>' )
            for (k,v) in atest.getParameters().items():
                fp.write( ' ' + k + '=' + v )
            fp.write( '</code></li>\n' )
            kwlist = atest.getKeywords() + \
                     self.statushandler.getResultsKeywords( atest )
            fp.write( '  <li>Keywords: <code>' + ' '.join( kwlist ) + \
                       '</code></li>\n' )
            xs = outpututils.XstatusString( self.statushandler,
                                            atest, self.testdir, cwd )
            fp.write( '  <li>Status: <code>' + xs + '</code></li>\n' )
            fp.write( '  <li> Files:' )
            if os.path.exists(reltdir):
                for f in os.listdir(reltdir):
                    fp.write( ' <a href="file:' + pjoin(reltdir,f) + \
                              '" type="text/plain">' + f + '</a>' )
            fp.write( '</li>\n' )
            fp.write( "</ul>\n" )
            fp.write( "</li>\n" )

        fp.write( '  </ul>\n' )