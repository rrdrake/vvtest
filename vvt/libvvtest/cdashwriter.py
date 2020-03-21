#!/usr/bin/env python

# Copyright 2018 National Technology & Engineering Solutions of Sandia, LLC
# (NTESS). Under the terms of Contract DE-NA0003525 with NTESS, the U.S.
# Government retains certain rights in this software.

import os, sys
import time
from os.path import join as pjoin
from os.path import normpath, abspath

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

    def setOutputDate(self, datestamp):
        ""
        self.datestamp = datestamp

    def prerun(self, atestlist, runinfo, verbosity):
        ""
        pass

    def midrun(self, atestlist, runinfo):
        ""
        pass

    def postrun(self, atestlist, runinfo):
        ""
        if self.outurl:
            self._dispatch_submission( atestlist, runinfo )
        else:
            self._write_files( atestlist, runinfo )

    def info(self, atestlist, runinfo):
        ""
        if self.outurl:
            self._dispatch_submission( atestlist, runinfo )
        else:
            self._write_files( atestlist, runinfo )

    def _write_files(self, atestlist, runinfo):
        ""
        if not os.path.isdir( self.outdir ):
            os.mkdir( self.outdir )

        try:
            self._convert_files( self.outdir, atestlist, runinfo )
        finally:
            self.permsetter.recurse( self.outdir )

    def _convert_files(self, destdir, atestlist, runinfo):
        ""
        tcaseL = atestlist.getActiveTests( self.sortspec )

        pass

    def _dispatch_submission(self, atestlist, runinfo):
        ""
        try:
            pass

        except Exception as e:
            print3( '\n*** WARNING: error submitting CDash results:',
                    str(e), '\n' )


def is_http_url( destination ):
    ""
    if os.path.exists( destination ):
        return False
    elif destination.startswith( 'http://' ) or \
         destination.startswith( 'https://' ):
        return True
    else:
        return False
