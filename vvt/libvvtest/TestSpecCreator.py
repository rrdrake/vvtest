#!/usr/bin/env python

# Copyright 2018 National Technology & Engineering Solutions of Sandia, LLC
# (NTESS). Under the terms of Contract DE-NA0003525 with NTESS, the U.S.
# Government retains certain rights in this software.

import os, sys
import re
import string

from . import xmlwrapper
from . import TestSpec
from . import FilterExpressions

from .ScriptReader import ScriptReader
from .errors import TestSpecError

from .parseutil import create_dependency_result_expression

import parsexml
import parsevvt


class TestCreator:

    def __init__(self, platname, optionlist):
        ""
        self.evaluator = ExpressionEvaluator( platname, optionlist )

    def fromFile(self, rootpath, relpath, force_params):
        """
        The 'rootpath' is the top directory of the file scan.  The 'relpath' is
        the name of the test file relative to 'rootpath' (it must not be an
        absolute path).  If 'force_params' is not None, then any parameters in
        the test that are in the 'force_params' dictionary have their values
        replaced for that parameter name.
        
        Returns a list of TestSpec objects, including a "parent" test if needed.
        """
        tests = create_testlist( self.evaluator,
                                 rootpath,
                                 relpath,
                                 force_params )

        return tests

    def reparse(self, tspec):
        """
        Parses the test source file and resets the settings for the given test.
        The test name is not changed.  The parameters in the test XML file are
        not considered; instead, the parameters already defined in the test
        object are used.

        If the test XML contains bad syntax, a TestSpecError is raised.
        """
        reparse_test_object( self.evaluator, tspec )


class ExpressionEvaluator:
    """
    Script test headers or attributes in test XML can specify a word
    expression that must be evaluated during test parsing.  This class caches
    the current platform name and command line option list, and provides
    functions to evaluate platform and option expressions.
    """

    def __init__(self, platname, option_list):
        self.platname = platname
        self.option_list = option_list

    def getPlatformName(self):
        ""
        return self.platname

    def evaluate_platform_expr(self, expr):
        """
        Evaluate the given expression against the current platform name.
        """
        wx = FilterExpressions.WordExpression(expr)
        return wx.evaluate( self._equals_platform )

    def _equals_platform(self, platname):
        ""
        if self.platname != None:
          return platname == self.platname
        return True

    def evaluate_option_expr(self, word_expr):
        """
        Evaluate the given expression against the list of command line options.
        """
        return word_expr.evaluate( self.option_list.count )


def create_testlist( evaluator, rootpath, relpath, force_params ):
    """
    Can use a (nested) rtest element to cause another test to be defined.
        
        <rtest name="mytest">
          <rtest name="mytest_fast"/>
          ...
        </rtest>

    then use the testname="..." attribute to filter XML elements.

        <keywords testname="mytest_fast"> fast </keywords>
        <keywords testname="mytest"> long </keywords>

        <parameters testname="mytest" np="1 2 4 8 16 32 64 128 256 512"/>
        <parameters testname="mytest_fast" np="1 2 4 8"/>
        
        <execute testname="mytest_fast" name="exodiff"> ... </execute>

        <analyze testname="mytest">
          ...
        </analyze>
        <analyze testname="mytest_fast">
          ...
        </analyze>
    """
    assert not os.path.isabs( relpath )

    fname = os.path.join( rootpath, relpath )
    ext = os.path.splitext( relpath )[1]

    if ext == '.xml':

        filedoc = read_xml_file( fname )
        
        nameL = parsexml.testNameList( filedoc )
        if nameL == None:
            return []
        
        tL = []
        for tname in nameL:
            L = createXmlTest( tname, filedoc, rootpath, relpath,
                               force_params, evaluator )
            tL.extend( L )
    
    elif ext == '.vvt':
        
        vspecs = ScriptReader( fname )
        nameL = parsevvt.testNameList_scr( vspecs )
        tL = []
        for tname in nameL:
            L = createScriptTest( tname, vspecs, rootpath, relpath,
                                  force_params, evaluator )
            tL.extend( L )

    else:
        raise Exception( "invalid file extension: "+ext )

    for tspec in tL:
        tspec.setConstructionCompleted()

    return tL


def read_xml_file( filename ):
    ""
    docreader = xmlwrapper.XmlDocReader()

    try:
        filedoc = docreader.readDoc( filename )
    except xmlwrapper.XmlError:
        raise TestSpecError( str( sys.exc_info()[1] ) )

    return filedoc


def createXmlTest( tname, filedoc, rootpath, relpath, force_params, evaluator ):
    ""
    pset = parsexml.parseTestParameters( filedoc, tname, evaluator, force_params )
    numparams = len( pset.getParameters() )

    # create the test instances

    testL = generate_test_objects( tname, rootpath, relpath, pset )

    if len(testL) > 0:
        # check for parameterize/analyze

        t = testL[0]

        analyze_spec = parsexml.parseAnalyze( t, filedoc, evaluator )

        if analyze_spec:
            if numparams == 0:
                raise TestSpecError( 'an analyze requires at least one ' + \
                                     'parameter to be defined' )

            # create an analyze test
            parent = t.makeParent()
            parent.setParameterSet( pset )
            testL.append( parent )

            parent.setAnalyzeScript( analyze_spec )

    # parse and set the rest of the XML file for each test
    
    for t in testL:
        parsexml.parseKeywords ( t, filedoc, tname )
        parsexml.parse_include_platform( t, filedoc )
        parsexml.parseTimeouts ( t, filedoc, evaluator )
        parsexml.parseExecuteList( t, filedoc, evaluator )
        parsexml.parseFiles    ( t, filedoc, evaluator )
        parsexml.parseBaseline ( t, filedoc, evaluator )

    return testL


def createScriptTest( tname, vspecs, rootpath, relpath,
                      force_params, evaluator ):
    ""
    pset = parsevvt.parseTestParameters_scr( vspecs, tname, evaluator, force_params )

    testL = generate_test_objects( tname, rootpath, relpath, pset )

    mark_staged_tests( pset, testL )

    check_add_analyze_test( pset, testL, vspecs, evaluator )

    for t in testL:
        parsevvt.parseKeywords_scr( t, vspecs, tname )
        parsevvt.parse_enable( t, vspecs )
        parsevvt.parseFiles_scr( t, vspecs, evaluator )
        parsevvt.parseTimeouts_scr( t, vspecs, evaluator )
        parsevvt.parseBaseline_scr( t, vspecs, evaluator )
        parsevvt.parseDependencies_scr( t, vspecs, evaluator )
        parsevvt.parse_preload_label( t, vspecs, evaluator )

    return testL


def generate_test_objects( tname, rootpath, relpath, pset ):
    ""
    testL = []

    numparams = len( pset.getParameters() )
    if numparams == 0:
        t = TestSpec.TestSpec( tname, rootpath, relpath )
        testL.append(t)

    else:
        # take a cartesian product of all the parameter values
        for pdict in pset.getInstances():
            # create the test and add to test list
            t = TestSpec.TestSpec( tname, rootpath, relpath )
            t.setParameters( pdict )
            t.setParameterTypes( pset.getParameterTypeMap() )
            testL.append(t)

    return testL


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


def check_add_analyze_test( pset, testL, vspecs, evaluator ):
    ""
    if len(testL) > 0:

        t = testL[0]

        analyze_spec = parsevvt.parseAnalyze_scr( t, vspecs, evaluator )

        if analyze_spec:

            numparams = len( pset.getParameters() )
            if numparams == 0:
                raise TestSpecError( 'an analyze requires at least one ' + \
                                     'parameter to be defined' )

            # create an analyze test
            parent = t.makeParent()
            parent.setParameterSet( pset )
            testL.append( parent )

            parent.setAnalyzeScript( analyze_spec )
            if not analyze_spec.startswith('-'):
                parent.addLinkFile( analyze_spec )


def reparse_test_object( evaluator, testobj ):
    """
    Given a TestSpec object, this function opens the original test file,
    parses, and overwrite the test contents.
    """
    fname = testobj.getFilename()
    ext = os.path.splitext( fname )[1]

    if ext == '.xml':

        filedoc = read_xml_file( fname )

        # run through the test name logic to check XML validity
        nameL = parsexml.testNameList(filedoc)

        tname = testobj.getName()

        parsexml.parse_include_platform( testobj, filedoc )

        if testobj.isAnalyze():
            analyze_spec = parsexml.parseAnalyze( testobj, filedoc, evaluator )
            testobj.setAnalyzeScript( analyze_spec )

        parsexml.parseKeywords( testobj, filedoc, tname )
        parsexml.parseFiles( testobj, filedoc, evaluator )
        parsexml.parseTimeouts( testobj, filedoc, evaluator )
        parsexml.parseExecuteList( testobj, filedoc, evaluator )
        parsexml.parseBaseline( testobj, filedoc, evaluator )

    elif ext == '.vvt':

        vspecs = ScriptReader( fname )

        # run through the test name logic to check validity
        nameL = parsevvt.testNameList_scr( vspecs )

        tname = testobj.getName()

        parsevvt.parse_enable( testobj, vspecs )

        pset = parsevvt.parseTestParameters_scr( vspecs, tname, evaluator, None )

        type_map = pset.getParameterTypeMap()
        testobj.setParameterTypes( type_map )

        if pset.getStagedGroup():
            mark_staged_tests( pset, [ testobj ] )

        if testobj.isAnalyze():
            testobj.getParameterSet().setParameterTypeMap( type_map )

            analyze_spec = parsevvt.parseAnalyze_scr( testobj, vspecs, evaluator )
            testobj.setAnalyzeScript( analyze_spec )
            if not analyze_spec.startswith('-'):
                testobj.addLinkFile( analyze_spec )

        parsevvt.parseKeywords_scr( testobj, vspecs, tname )
        parsevvt.parseFiles_scr( testobj, vspecs, evaluator )
        parsevvt.parseTimeouts_scr( testobj, vspecs, evaluator )
        parsevvt.parseBaseline_scr( testobj, vspecs, evaluator )
        parsevvt.parseDependencies_scr( testobj, vspecs, evaluator )
        parsevvt.parse_preload_label( testobj, vspecs, evaluator )

    else:
        raise Exception( "invalid file extension: "+ext )

    testobj.setConstructionCompleted()


##########################################################################
