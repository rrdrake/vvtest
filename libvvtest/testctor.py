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
        self.idgen = testid.IDGenerator( None )

    def setShorten(self, numchars):
        ""
        self.idgen = testid.IDGenerator( numchars )

    def getIDGenerator(self):
        ""
        return self.idgen

    def makeIDGenerator(self, numchars):
        ""
        return testid.IDGenerator( numchars )

    def makeTestSpec(self, testname, rootpath, filepath):
        ""
        return testspec.TestSpec( testname, rootpath, filepath, self.idgen )
