#!/usr/bin/env python

# Copyright 2018 National Technology & Engineering Solutions of Sandia, LLC
# (NTESS). Under the terms of Contract DE-NA0003525 with NTESS, the U.S.
# Government retains certain rights in this software.

import os, sys

from . import TestSpec
from . import FilterExpressions

from .ScriptReader import ScriptReader
from .errors import TestSpecError

from .parseutil import create_dependency_result_expression

from . import parsexml
from . import parsevvt
from . import parseutil


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

        filedoc = parsexml.read_xml_file( fname )

        nameL = parsexml.parse_test_names( filedoc )
        if nameL == None:
            return []

        tL = []
        for tname in nameL:
            L = create_xml_test( tname, filedoc, rootpath, relpath,
                                 force_params, evaluator )
            tL.extend( L )

    elif ext == '.vvt':

        vspecs = ScriptReader( fname )
        nameL = parsevvt.parse_test_names( vspecs )
        tL = []
        for tname in nameL:
            L = create_script_test( tname, vspecs, rootpath, relpath,
                                    force_params, evaluator )
            tL.extend( L )

    else:
        raise Exception( "invalid file extension: "+ext )

    for tspec in tL:
        tspec.setConstructionCompleted()

    return tL


def create_xml_test( tname, filedoc, rootpath, relpath, force_params, evaluator ):
    ""
    pset = parsexml.parse_parameterize( filedoc, tname, evaluator, force_params )
    numparams = len( pset.getParameters() )

    # create the test instances

    testL = generate_test_objects( tname, rootpath, relpath, pset )

    if len(testL) > 0:
        # check for parameterize/analyze

        t = testL[0]

        analyze_spec = parsexml.parse_analyze( t, filedoc, evaluator )

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
        parsexml.parse_keywords( t, filedoc, tname )
        parsexml.parse_include_platform( t, filedoc )
        parsexml.parse_timeouts( t, filedoc, evaluator )
        parsexml.parse_execute_list( t, filedoc, evaluator )
        parsexml.parse_working_files( t, filedoc, evaluator )
        parsexml.parse_baseline( t, filedoc, evaluator )

    return testL


def create_script_test( tname, vspecs, rootpath, relpath,
                        force_params, evaluator ):
    ""
    pset = parsevvt.parse_parameterize( vspecs, tname, evaluator, force_params )

    testL = generate_test_objects( tname, rootpath, relpath, pset )

    parseutil.mark_staged_tests( pset, testL )

    parsevvt.check_add_analyze_test( pset, testL, vspecs, evaluator )

    for t in testL:
        parsevvt.parse_keywords( t, vspecs, tname )
        parsevvt.parse_enable( t, vspecs )
        parsevvt.parse_working_files( t, vspecs, evaluator )
        parsevvt.parse_timeouts( t, vspecs, evaluator )
        parsevvt.parse_baseline( t, vspecs, evaluator )
        parsevvt.parse_dependencies( t, vspecs, evaluator )
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


def reparse_test_object( evaluator, testobj ):
    """
    Given a TestSpec object, this function opens the original test file,
    parses, and overwrite the test contents.
    """
    fname = testobj.getFilename()
    ext = os.path.splitext( fname )[1]

    if ext == '.xml':

        filedoc = parsexml.read_xml_file( fname )

        # run through the test name logic to check XML validity
        nameL = parsexml.parse_test_names(filedoc)

        tname = testobj.getName()

        parsexml.parse_include_platform( testobj, filedoc )

        if testobj.isAnalyze():
            analyze_spec = parsexml.parse_analyze( testobj, filedoc, evaluator )
            testobj.setAnalyzeScript( analyze_spec )

        parsexml.parse_keywords( testobj, filedoc, tname )
        parsexml.parse_working_files( testobj, filedoc, evaluator )
        parsexml.parse_timeouts( testobj, filedoc, evaluator )
        parsexml.parse_execute_list( testobj, filedoc, evaluator )
        parsexml.parse_baseline( testobj, filedoc, evaluator )

    elif ext == '.vvt':

        vspecs = ScriptReader( fname )

        # run through the test name logic to check validity
        nameL = parsevvt.parse_test_names( vspecs )

        tname = testobj.getName()

        parsevvt.parse_enable( testobj, vspecs )

        pset = parsevvt.parse_parameterize( vspecs, tname, evaluator, None )

        type_map = pset.getParameterTypeMap()
        testobj.setParameterTypes( type_map )

        if pset.getStagedGroup():
            parseutil.mark_staged_tests( pset, [ testobj ] )

        if testobj.isAnalyze():
            testobj.getParameterSet().setParameterTypeMap( type_map )

            analyze_spec = parsevvt.parse_analyze( testobj, vspecs, evaluator )
            testobj.setAnalyzeScript( analyze_spec )
            if not analyze_spec.startswith('-'):
                testobj.addLinkFile( analyze_spec )

        parsevvt.parse_keywords( testobj, vspecs, tname )
        parsevvt.parse_working_files( testobj, vspecs, evaluator )
        parsevvt.parse_timeouts( testobj, vspecs, evaluator )
        parsevvt.parse_baseline( testobj, vspecs, evaluator )
        parsevvt.parse_dependencies( testobj, vspecs, evaluator )
        parsevvt.parse_preload_label( testobj, vspecs, evaluator )

    else:
        raise Exception( "invalid file extension: "+ext )

    testobj.setConstructionCompleted()
