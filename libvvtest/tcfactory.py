#!/usr/bin/env python

# Copyright 2018 National Technology & Engineering Solutions of Sandia, LLC
# (NTESS). Under the terms of Contract DE-NA0003525 with NTESS, the U.S.
# Government retains certain rights in this software.

from .testcase import TestCase


class TestCaseFactory:

    def __init__(self, nodesize=None):
        ""
        self.nodesize = nodesize

    def new(self, tspec):
        ""
        return TestCase( tspec, self.nodesize )
