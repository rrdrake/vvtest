#!/usr/bin/env python

# Copyright 2018 National Technology & Engineering Solutions of Sandia, LLC
# (NTESS). Under the terms of Contract DE-NA0003525 with NTESS, the U.S.
# Government retains certain rights in this software.

import os

from .errors import TestSpecError
from .staging import mark_staged_tests
from .parsevvt import ScriptTestParser
from .parsexml import XMLTestParser


class TestCreator:

    def __init__(self, idtraits={},
                       platname=os.uname()[0],
                       optionlist=[],
                       force_params=None ):
        """
        If 'force_params' is not None, then any parameters in a test that
        are in the 'force_params' dictionary will have their values replaced
        for that parameter name.
        """
        self.idtraits = idtraits
        self.platname = platname
        self.optionlist = optionlist
        self.force_params = force_params

    def getValidFileExtensions(self, specform=None):
        ""
        if specform == 'vvt':
            return ['.vvt']
        elif specform == 'xml':
            return ['.xml']
        else:
            return ['.xml','.vvt']

    def fromFile(self, relpath, rootpath=None):
        """
        The 'rootpath' is the top directory of the file scan.  The 'relpath' is
        the name of the test file relative to 'rootpath' (it must not be an
        absolute path).  

        Returns a list of TestSpec objects, including a "parent" test if needed.
        """
        assert not os.path.isabs( relpath )

        if not rootpath:
            rootpath = os.getcwd()

        maker = self.create_test_maker( relpath, rootpath, False )

        tests = maker.createTests()

        return tests

    def reparse(self, tspec):
        """
        Parses the test source file and resets the test specifications. The
        test name is not changed, and the parameters in the test source file
        are not considered.  Instead, the parameters already defined in the
        test object are used.

        A TestSpecError is raised if the file has an invalid specification.
        """
        maker = self.create_test_maker( tspec.getFilepath(),
                                        tspec.getRootpath(),
                                        strict=True )

        maker.reparseTest( tspec )

    def create_test_maker(self, relpath, rootpath, strict):
        ""
        form = map_extension_to_spec_form( relpath )

        if form == 'xml':
            parser = XMLTestParser( relpath, rootpath,
                                    self.idtraits,
                                    self.platname,
                                    self.optionlist,
                                    self.force_params,
                                    strict )

        else:
            assert form == 'script'

            parser = ScriptTestParser( relpath, rootpath,
                                       self.idtraits,
                                       self.platname,
                                       self.optionlist,
                                       self.force_params )

        maker = TestMaker( parser )

        return maker


def map_extension_to_spec_form( filepath ):
    ""
    if os.path.splitext( filepath )[1] == '.xml':
        return 'xml'
    else:
        return 'script'


class TestMaker:

    def __init__(self, parser):
        ""
        self.parser = parser

    def createTests(self):
        ""
        nameL = self.parser.parseTestNames()

        self.tests = []
        for tname in nameL:
            L = self.create_test_list( tname )
            self.tests.extend( L )

        return self.tests

    def reparseTest(self, tspec):
        ""
        # run through the test name logic to check validity
        self.parser.parseTestNames()

        tname = tspec.getName()

        old_pset = tspec.getParameterSet()
        new_pset = self.parser.parseParameterSet( tname )
        new_pset.intersectionFilter( old_pset.getInstances() )
        tspec.setParameterSet( new_pset )

        if new_pset.getStagedGroup():
            mark_staged_tests( new_pset, [ tspec ] )

        if tspec.isAnalyze():
            analyze_spec = self.parser.parseAnalyzeSpec( tname )
            tspec.setAnalyzeScript( analyze_spec )

        self.parser.parseTestInstance( tspec )

    def create_test_list(self, tname):
        ""
        pset = self.parser.parseParameterSet( tname )

        testL = self.generate_test_objects( tname, pset )

        mark_staged_tests( pset, testL )

        analyze_spec = self.parser.parseAnalyzeSpec( tname )
        self.check_add_analyze_test( analyze_spec, tname, pset, testL )

        for t in testL:
            self.parser.parseTestInstance( t )

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

        parent = self.parser.makeTestInstance( testname )

        parent.setIsAnalyze()
        parent.setParameterSet( paramset )
        parent.setAnalyzeScript( analyze_spec )

        return parent

    def generate_test_objects(self, tname, pset):
        ""
        testL = []

        if len( pset.getParameters() ) == 0:
            t = self.parser.makeTestInstance( tname )
            testL.append(t)

        else:
            # take a cartesian product of all the parameter values
            for pdict in pset.getInstances():
                # create the test and add to test list
                t = self.parser.makeTestInstance( tname )
                t.setParameters( pdict )
                t.setParameterSet( pset )
                testL.append(t)

        return testL
