#!/usr/bin/env python

# Copyright 2018 National Technology & Engineering Solutions of Sandia, LLC
# (NTESS). Under the terms of Contract DE-NA0003525 with NTESS, the U.S.
# Government retains certain rights in this software.

import os, sys
from os.path import join as pjoin

from . import testspec
from . import FilterExpressions

from .ScriptReader import ScriptReader
from .errors import TestSpecError

from . import parsexml
from . import parsevvt
from . import staging
from .paramset import ParameterSet


class TestCreator:

    def __init__(self, testctor, platname=os.uname()[0], optionlist=[]):
        ""
        self.tctor = testctor
        self.evaluator = ExpressionEvaluator( platname, optionlist )

    def fromFile(self, rootpath, relpath, force_params=None):
        """
        The 'rootpath' is the top directory of the file scan.  The 'relpath' is
        the name of the test file relative to 'rootpath' (it must not be an
        absolute path).  If 'force_params' is not None, then any parameters in
        the test that are in the 'force_params' dictionary have their values
        replaced for that parameter name.

        Returns a list of TestSpec objects, including a "parent" test if needed.
        """
        assert not os.path.isabs( relpath )

        form = map_extension_to_spec_form( relpath )

        ctor = create_test_constructor( form, rootpath, relpath,
                                        self.evaluator, self.tctor,
                                        force_params )

        ctor.readFile()
        tests = ctor.createTests()

        return tests

    def reparse(self, tspec):
        """
        Parses the test source file and resets the settings for the given test.
        The test name is not changed, and the parameters in the test source file
        are not considered.  Instead, the parameters already defined in the test
        object are used.

        A TestSpecError is raised if the file has an invalid specification.
        """
        form = map_extension_to_spec_form( tspec.getFilepath() )

        ctor = create_test_constructor( form, tspec.getRootpath(),
                                              tspec.getFilepath(),
                                              self.evaluator,
                                              self.tctor,
                                              None )

        ctor.readFile( strict=True )
        ctor.reparseTest( tspec )


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


class TestMaker:

    def __init__(self, rootpath, relpath, evaluator, testctor,
                       force_params={} ):
        ""
        self.root = rootpath
        self.fpath = relpath
        self.force = force_params
        self.evaluator = evaluator

        self.tctor = testctor

        self.source = None

    def createTests(self):
        ""
        nameL = self.parseTestNames()

        self.tests = []
        for tname in nameL:
            L = self.create_test_list( tname )
            self.tests.extend( L )

        return self.tests

    def reparseTest(self, tspec):
        ""
        # run through the test name logic to check validity
        self.parseTestNames()

        tname = tspec.getName()

        old_pset = tspec.getParameterSet()
        new_pset = self.parseParameterSet( tname )
        new_pset.intersectionFilter( old_pset.getInstances() )
        tspec.setParameterSet( new_pset )

        if new_pset.getStagedGroup():
            staging.mark_staged_tests( new_pset, [ tspec ], self.tctor )

        if tspec.isAnalyze():
            analyze_spec = self.parseAnalyzeSpec( tname )
            tspec.setAnalyzeScript( analyze_spec )

        inst = self.make_parsing_instance( tspec )
        self.parseTestInstance( inst )

    def create_test_list(self, tname):
        ""
        pset = self.parseParameterSet( tname )

        testL = self.generate_test_objects( tname, pset )

        staging.mark_staged_tests( pset, testL, self.tctor )

        analyze_spec = self.parseAnalyzeSpec( tname )
        self.check_add_analyze_test( analyze_spec, tname, pset, testL )

        for t in testL:
            inst = self.make_parsing_instance( t )
            self.parseTestInstance( inst )

        return testL

    def check_add_analyze_test(self, analyze_spec, tname, pset, testL):
        ""
        if analyze_spec:
            parent = self.make_analyze_test( analyze_spec, tname, pset )
            testL.append( parent )

    def make_analyze_test(self, analyze_spec, testname, paramset):
        ""
        if len( paramset.getParameters() ) == 0:
            raise TestSpecError( 'an analyze requires at least one ' + \
                                 'parameter to be defined' )

        parent = self.tctor.makeTestSpec( testname, self.root, self.fpath )

        parent.setIsAnalyze()
        parent.setParameterSet( paramset )
        parent.setAnalyzeScript( analyze_spec )

        return parent

    def make_parsing_instance(self, tspec):
        ""
        inst = ParsingInstance( testname=tspec.getName(),
                                params=tspec.getParameters(),
                                tfile=tspec,
                                source=self.source,
                                evaluator=self.evaluator )

        return inst

    def generate_test_objects(self, tname, pset):
        ""
        testL = []

        if len( pset.getParameters() ) == 0:
            t = self.tctor.makeTestSpec( tname, self.root, self.fpath )
            testL.append(t)

        else:
            # take a cartesian product of all the parameter values
            for pdict in pset.getInstances():
                # create the test and add to test list
                t = self.tctor.makeTestSpec( tname, self.root, self.fpath )
                t.setParameters( pdict )
                t.setParameterSet( pset )
                testL.append(t)

        return testL


class ParsingInstance:

    def __init__(self, testname='',
                       params={},
                       tfile=None,
                       source=None,
                       evaluator=None ):
        ""
        self.testname = testname
        self.params = params
        self.tfile = tfile
        self.source = source
        self.evaluator = evaluator


class XMLTestMaker( TestMaker ):

    def readFile(self, strict=False):
        ""
        fname = pjoin( self.root, self.fpath )
        self.source = parsexml.read_xml_file( fname, strict )

    def parseTestNames(self):
        ""
        return parsexml.parse_test_names( self.source )

    def parseParameterSet(self, tname):
        ""
        pset = ParameterSet()
        parsexml.parse_parameterize( pset, self.source, tname,
                                     self.evaluator, self.force )
        return pset

    def parseAnalyzeSpec(self, tname):
        ""
        return parsexml.parse_analyze( tname, self.source, self.evaluator )

    def parseTestInstance(self, inst):
        ""
        parsexml.parse_xml_test( inst )


class ScriptTestMaker( TestMaker ):

    def readFile(self, strict=False):
        ""
        fname = pjoin( self.root, self.fpath )
        self.source = ScriptReader( fname )

    def parseTestNames(self):
        ""
        return parsevvt.parse_test_names( self.source )

    def parseParameterSet(self, tname):
        ""
        pset = ParameterSet()
        parsevvt.parse_parameterize( pset, self.source, tname,
                                     self.evaluator, self.force )
        return pset

    def parseAnalyzeSpec(self, tname):
        ""
        return parsevvt.parse_analyze( tname, self.source, self.evaluator )

    def parseTestInstance(self, inst):
        ""
        parsevvt.parse_vvt_test( inst )


def map_extension_to_spec_form( filepath ):
    ""
    if os.path.splitext( filepath )[1] == '.xml':
        return 'xml'
    else:
        return 'script'


def create_test_constructor( spec_form, rootpath, relpath,
                             evaluator, testctor, force_params ):
    ""
    if spec_form == 'xml':
        ctor = XMLTestMaker( rootpath, relpath, evaluator, testctor,
                             force_params )

    elif spec_form == 'script':
        ctor = ScriptTestMaker( rootpath, relpath, evaluator, testctor,
                                force_params )

    else:
        raise Exception( "invalid test specification form: "+spec_form )

    return ctor
