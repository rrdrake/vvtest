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

    def __init__(self, destination, results_test_dir, permsetter, cdashutil):
        ""
        self.dest = destination
        self.testdir = results_test_dir
        self.permsetter = permsetter
        self.cdashutil = cdashutil

        self.datestamp = None
        self.proj = None

    def setOutputDate(self, datestamp):
        ""
        self.datestamp = datestamp

    def setCDashProjectName(self, proj):
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
        fmtr = self.cdashutil.TestResultsFormatter()
        set_global_data( fmtr, runinfo )
        set_test_list( fmtr, atestlist )
        return fmtr

    def _write_data(self, fmtr, runinfo):
        ""
        if is_http_url( self.dest ):

            fname = pjoin( self.testdir, 'vvtest_cdash_submit.xml' )

            try:
                fmtr.writeToFile( fname )
                self.permsetter.set( fname )
                assert self.proj, 'CDash project name not set'
                self.cdashutil.submit_file( self.dest, self.proj, fname )

            except Exception as e:
                print3( '\n*** WARNING: error submitting CDash results:',
                        str(e), '\n' )

        else:
            fmtr.writeToFile( self.dest )
            self.permsetter.set( self.dest )


def set_global_data( fmtr, runinfo ):
    ""
    tm = runinfo.get( 'startepoch', time.time() )

    rdir = None
    if 'rundir' in runinfo:
        rdir = basename( runinfo['rundir'] )

    fmtr.setBuildID( build_date=tm,
                     site_name=runinfo.get( 'hostname', None ),
                     build_name=rdir )

    fmtr.setTime( tm, runinfo.get( 'finishepoch', None ) )


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
