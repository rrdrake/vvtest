#!/usr/bin/env python

# Copyright 2018 National Technology & Engineering Solutions of Sandia, LLC
# (NTESS). Under the terms of Contract DE-NA0003525 with NTESS, the U.S.
# Government retains certain rights in this software.

import os, sys

from . import testspec
from . import parseutil


def mark_staged_tests( pset, testL, testctor ):
    """
    1. each test must be told which parameter names form the staged set
    2. the first and last tests in a staged set must be marked as such
    3. each staged test "depends on" the previous staged test
    """
    if pset.getStagedGroup():

        oracle = StagingOracle( pset.getStagedGroup(), testctor )

        for tspec in testL:

            set_stage_params( tspec, oracle )

            prev = oracle.findPreviousStageDisplayID( tspec )
            if prev:
                add_staged_dependency( tspec, prev )


def set_stage_params( tspec, oracle ):
    ""
    idx = oracle.getStageIndex( tspec )
    is_first = ( idx == 0 )
    is_last = ( idx == oracle.numStages() - 1 )

    names = oracle.getStagedParameterNames()

    tspec.setStagedParameters( is_first, is_last, *names )


def add_staged_dependency( from_tspec, to_display_string ):
    ""
    wx = parseutil.create_dependency_result_expression( None )
    from_tspec.addDependency( to_display_string, wx )


class StagingOracle:

    def __init__(self, stage_group, testctor):
        ""
        self.param_nameL = stage_group[0]
        self.param_valueL = stage_group[1]

        self.stage_values = [ vals[0] for vals in self.param_valueL ]

        self.tctor = testctor

    def getStagedParameterNames(self):
        ""
        return self.param_nameL

    def numStages(self):
        ""
        return len( self.param_valueL )

    def getStageIndex(self, tspec):
        ""
        stage_name = self.param_nameL[0]
        stage_val = tspec.getParameterValue( stage_name )
        idx = self.stage_values.index( stage_val )
        return idx

    def findPreviousStageDisplayID(self, tspec):
        ""
        idx = self.getStageIndex( tspec )
        if idx > 0:

            paramD = self._create_params_for_stage( tspec, idx-1 )

            idgen = self.tctor.getIDGenerator()
            tid = idgen.makeID( tspec.getName(),
                                tspec.getFilepath(),
                                paramD,
                                self.param_nameL )
            displ = tid.computeDisplayString()

            return displ

        return None

    def _create_params_for_stage(self, tspec, stage_idx):
        ""
        paramD = tspec.getParameters()
        for i,pname in enumerate( self.param_nameL ):
            pval = self.param_valueL[ stage_idx ][i]
            paramD[ pname ] = pval

        return paramD


def tests_are_related_by_staging( tspec1, tspec2 ):
    ""
    if tspec1.getFilename() == tspec2.getFilename():

        idgen1 = tspec1.getTestID()
        idgen2 = tspec2.getTestID()

        names1 = idgen1.getStageNames()
        names2 = idgen2.getStageNames()

        if names1 and names1 == names2:

            id1 = idgen1.computeID( compress_stage=True )
            id2 = idgen2.computeID( compress_stage=True )

            return id1 == id2

    return False
