#!/usr/bin/env python

# Copyright 2018 National Technology & Engineering Solutions of Sandia, LLC
# (NTESS). Under the terms of Contract DE-NA0003525 with NTESS, the U.S.
# Government retains certain rights in this software.

import os, sys
import time
from os.path import join as pjoin
from os.path import basename

from . import outpututils
print3 = outpututils.print3


class CDashWriter:

    def __init__(self, destination, results_test_dir, permsetter):
        ""
        self.dest = destination
        self.testdir = results_test_dir
        self.permsetter = permsetter

        self.formatter = None
        self.submitter = None

        self.datestamp = None
        self.proj = None

    def setCDashFormatter(self, formatter_type, submitter_type):
        ""
        self.formatter = formatter_type
        self.submitter = submitter_type

    def setResultsDate(self, datestamp):
        ""
        self.datestamp = datestamp

    def setProjectName(self, proj):
        ""
        self.proj = proj

    def prerun(self, atestlist, runinfo, verbosity):
        ""
        pass

    def midrun(self, atestlist, runinfo):
        ""
        pass

    def postrun(self, atestlist, runinfo):
        ""
        fmtr = self._create_and_fill_formatter( atestlist, runinfo )
        self._write_data( fmtr, runinfo )

    def info(self, atestlist, runinfo):
        ""
        assert False

    def _create_and_fill_formatter(self, atestlist, runinfo):
        ""
        fmtr = self.formatter()
        set_global_data( fmtr, self.datestamp, runinfo )
        set_test_list( fmtr, atestlist )
        return fmtr

    def _write_data(self, fmtr, runinfo):
        ""
        if is_http_url( self.dest ):

            fname = pjoin( self.testdir, 'vvtest_cdash_submit.xml' )

            try:
                self._write_file( fmtr, fname )

                assert self.proj, 'CDash project name not set'
                sub = self.submitter( self.dest, self.proj )
                sub.send( fname )

            except Exception as e:
                print3( '\n*** WARNING: error submitting CDash results:',
                        str(e), '\n' )

        else:
            self._write_file( fmtr, self.dest )

    def _write_file(self, fmtr, filename):
        ""
        fmtr.writeToFile( filename )
        self.permsetter.set( filename )


def set_global_data( fmtr, date_stamp, runinfo ):
    ""
    if date_stamp:
        bdate = date_stamp
        tstart = runinfo.get( 'startepoch', bdate )
    else:
        bdate = runinfo.get( 'startepoch', time.time() )
        tstart = bdate

    rdir = None
    if 'rundir' in runinfo:
        rdir = basename( runinfo['rundir'] )

    fmtr.setBuildID( build_date=bdate,
                     site_name=runinfo.get( 'hostname', None ),
                     build_name=rdir )

    fmtr.setTime( tstart, runinfo.get( 'finishepoch', None ) )


def set_test_list( fmtr, atestlist ):
    ""
    tcaseL = atestlist.getActiveTests()

    for tcase in tcaseL:

        tspec = tcase.getSpec()
        tstat = tcase.getStat()

        vvstat = tstat.getResultStatus()

        if vvstat == 'notrun':
            fmtr.addTest( tspec.getDisplayString(),
                          status='notrun' )

        elif vvstat == 'pass':
            fmtr.addTest( tspec.getDisplayString(),
                          status='passed',
                          runtime=tstat.getRuntime( None ) )

        else:
            fmtr.addTest( tspec.getDisplayString(),
                          status='failed',
                          runtime=tstat.getRuntime( None ),
                          detail=vvstat )

            # TODO: add output=... here
            #       the output could be an ls -ltra on the test results
            #       directory plus the execute.log file with the middle removed


def is_http_url( destination ):
    ""
    if os.path.exists( destination ):
        return False
    elif destination.startswith( 'http://' ) or \
         destination.startswith( 'https://' ):
        return True
    else:
        return False
