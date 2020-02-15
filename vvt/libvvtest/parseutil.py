#!/usr/bin/env python

# Copyright 2018 National Technology & Engineering Solutions of Sandia, LLC
# (NTESS). Under the terms of Contract DE-NA0003525 with NTESS, the U.S.
# Government retains certain rights in this software.

import os, sys
import re

from .errors import TestSpecError
from . import TestSpec
from .paramset import ParameterSet
from . import FilterExpressions


def evauate_testname_expr( testname, expr ):
    ""
    wx = FilterExpressions.WordExpression(expr)
    L = [ testname ]
    return wx.evaluate( L.count )


alphanum_chars  = 'abcdefghijklmnopqrstuvwxyz' + \
                  'ABCDEFGHIJKLMNOPQRSTUVWXYZ' + \
                  '0123456789_'
allowable_chars = alphanum_chars + '.-=+#@^%:~'


allowable_chars_dict = {}
for c in allowable_chars:
  allowable_chars_dict[c] = None

def allowable_string(s):
    ""
    for c in s:
      if c not in allowable_chars_dict:
        return 0
    return 1


alphanum_chars_dict = {}
for c in alphanum_chars:
  alphanum_chars_dict[c] = None

def allowable_variable(s):
    ""
    if s[:1] in ['0','1','2','3','4','5','6','7','8','9','_']:
      return 0
    for c in s:
      if c not in alphanum_chars_dict:
        return 0
    return 1


def variable_expansion( tname, platname, paramD, fL ):
    """
    Replaces shell style variables in the given file list with their values.
    For example $np or ${np} is replaced with 4.  Also replaces NAME and
    PLATFORM with their values.  The 'fL' argument can be a list of strings
    or a list of [string 1, string 2] pairs.  Dollar signs preceeded by a
    backslash are not expanded and the backslash is removed.
    """
    if platname == None: platname = ''
    
    if len(fL) > 0:
      
      # substitute parameter values for $PARAM, ${PARAM}, and {$PARAM} patterns;
      # also replace the special NAME variable with the name of the test and
      # PLATFORM with the name of the current platform
      for n,v in list(paramD.items()) + [('NAME',tname)] + [('PLATFORM',platname)]:
        pat1 = re.compile( '[{](?<![\\\\])[$]' + n + '[}]' )
        pat2 = re.compile( '(?<![\\\\])[$][{]' + n + '[}]' )
        pat3 = re.compile( '(?<![\\\\])[$]' + n + '(?![_a-zA-Z0-9])' )
        if type(fL[0]) == type([]):
          for fpair in fL:
            f,t = fpair
            f,n = pat1.subn( v, f )
            f,n = pat2.subn( v, f )
            f,n = pat3.subn( v, f )
            if t != None:
              t,n = pat1.subn( v, t )
              t,n = pat2.subn( v, t )
              t,n = pat3.subn( v, t )
            fpair[0] = f
            fpair[1] = t
            # TODO: replace escaped $ with a dollar
        else:
          for i in range(len(fL)):
            f = fL[i]
            f,n = pat1.subn( v, f )
            f,n = pat2.subn( v, f )
            f,n = pat3.subn( v, f )
            fL[i] = f
      
      # replace escaped dollar with just a dollar
      patD = re.compile( '[\\\\][$]' )
      if type(fL[0]) == type([]):
        for fpair in fL:
          f,t = fpair
          f,n = patD.subn( '$', f )
          if t != None:
            t,n = patD.subn( '$', t )
          fpair[0] = f
          fpair[1] = t
      else:
        for i in range(len(fL)):
          f = fL[i]
          f,n = patD.subn( '$', f )
          fL[i] = f


def check_forced_group_parameter( force_params, name_list, lineno ):
    ""
    if force_params != None:
        for n in name_list:
            if n in force_params:
                raise TestSpecError( 'cannot force a grouped ' + \
                                     'parameter name: "' + \
                                     n+'", line ' + str(lineno) )


def check_for_duplicate_parameter( paramlist, lineno ):
    ""
    for val in paramlist:
        if paramlist.count( val ) > 1:

            if is_list_or_tuple(val):
                dup = ','.join(val)
            else:
                dup = str(val)

            raise TestSpecError( 'duplicate parameter value: "'+dup + \
                                 '", line ' + str(lineno) )


def is_list_or_tuple( obj ):
    ""
    if type(obj) in [ type(()), type([]) ]:
        return True

    return False


def create_dependency_result_expression( attrs ):
    ""
    wx = None

    if attrs != None and 'result' in attrs:

        result = attrs['result'].strip()

        if result == '*':
            wx = FilterExpressions.WordExpression()
        else:
            wx = FilterExpressions.WordExpression( result )

    return wx


def mark_staged_tests( pset, testL ):
    """
    1. each test must be told which parameter names form the staged set
    2. the first and last tests in a staged set must be marked as such
    3. each staged test "depends on" the previous staged test
    """
    if pset.getStagedGroup():

        oracle = StagingOracle( pset.getStagedGroup() )

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
    wx = create_dependency_result_expression( None )
    from_tspec.addDependency( to_display_string, wx )


class StagingOracle:

    def __init__(self, stage_group):
        ""
        self.param_nameL = stage_group[0]
        self.param_valueL = stage_group[1]

        self.stage_values = [ vals[0] for vals in self.param_valueL ]

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

            paramD = tspec.getParameters()
            self._overwrite_with_stage_params( paramD, idx-1 )

            idgen = TestSpec.IDGenerator( tspec.getName(),
                                          tspec.getFilepath(),
                                          paramD,
                                          self.param_nameL )
            displ = idgen.computeDisplayString()

            return displ

        return None

    def _overwrite_with_stage_params(self, paramD, stage_idx):
        ""
        for i,pname in enumerate( self.param_nameL ):
            pval = self.param_valueL[ stage_idx ][i]
            paramD[ pname ] = pval
