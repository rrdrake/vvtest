#!/usr/bin/env python

# Copyright 2018 National Technology & Engineering Solutions of Sandia, LLC
# (NTESS). Under the terms of Contract DE-NA0003525 with NTESS, the U.S.
# Government retains certain rights in this software.

import os
from os.path import basename

from . import testid
from . import testspec


class TestConstructor:

    def __init__(self):
        ""
        pass

    def makeTestID(self, testname, filepath, params, staged_names):
        ""
        tid = testid.TestID( testname, filepath, params, staged_names )
        return tid

    def makeTestSpec(self, testname, rootpath, filepath):
        ""
        tspec = testspec.TestSpec( testname, rootpath, filepath, self.makeTestID )
        return tspec
