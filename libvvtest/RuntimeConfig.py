#!/usr/bin/env python

# Copyright 2018 National Technology & Engineering Solutions of Sandia, LLC
# (NTESS). Under the terms of Contract DE-NA0003525 with NTESS, the U.S.
# Government retains certain rights in this software.

import sys
sys.dont_write_bytecode = True
sys.excepthook = sys.__excepthook__
import os
import fnmatch
import re

from . import FilterExpressions


class RuntimeConfig:

    attr_init = {
        'vvtestdir'  : None,  # the top level vvtest directory
        'configdir'  : [],    # the configuration directory(ies)
        'exepath'    : None,  # the path to the executables
        'onopts'     : [],
        'offopts'    : [],
        'preclean'   : True,
        'postclean'  : False,
        'analyze'    : False,
        'logfile'    : True,
        'testargs'   : [],
    }

    def __init__(self, **kwargs ):
        ""
        self.attrs = {}

        self.platname = None
        self.default_platexpr = None
        self.platexpr = None
        self.apply_platexpr = True

        self.keyexpr = None

        self.paramexpr = None

        self.optlist = []

        self.maxsize = None
        self.apply_maxprocs = True
        self.apply_maxdevices = True

        self.include_tdd = False
        self.apply_tdd = True

        self.filesearch = None

        self.runtime_range = None
        self.runtime_sum = None

        for n,v in RuntimeConfig.attr_init.items():
            self.setAttr( n, v )

        for k,v in kwargs.items():
            self.setAttr( k, v )

    def setAttr(self, name, value):
        """
        Set the value of an attribute name (which must be known).
        """
        assert name in RuntimeConfig.attr_init
        self.attrs[name] = value

    def getAttr(self, name, *default):
        """
        Get the value of an attribute name.  A default value can be given
        and will be returned when the attribute name is not set.
        """
        if len(default) == 0:
            return self.attrs[name]
        return self.attrs.get( name, default[0] )

    def setPlatformName(self, name):
        ""
        self.platname = name
        # by default, the current platform is used as the expression
        self.default_platexpr = FilterExpressions.WordExpression( name )

    def getPlatformName(self):
        ""
        return self.platname

    def setPlatformExpression(self, expr):
        ""
        self.platexpr = expr

    def applyPlatformExpression(self, true_or_false):
        ""
        self.apply_platexpr = true_or_false

    def evaluate_platform_include(self, list_of_platform_expr):
        ""
        ok = True

        if self.apply_platexpr:
            if self.platexpr:
                expr = self.platexpr
            else:
                expr = self.default_platexpr

            # to evaluate the command line expression, each platform name in the
            # expression is evaluated using PlatformEvaluator.satisfies_platform()
            pev = PlatformEvaluator( list_of_platform_expr )
            ok = expr.evaluate( pev.satisfies_platform )

        return ok

    def setOptionList(self, list_of_options):
        ""
        if list_of_options:
            self.optlist = list( list_of_options )
        else:
            self.optlist = []

    def getOptionList(self):
        ""
        return self.optlist

    def setKeywordExpression(self, word_expr):
        ""
        self.keyexpr = word_expr

    def addResultsKeywordExpression(self, add_expr):
        """
        If a keyword expression already exists in this object and contains
        results keywords (such as "diff" or "notdone"), then do nothing.
        Otherwise AND the new expression to the existing.
        """
        if self.keyexpr == None:
            self.keyexpr = FilterExpressions.WordExpression( add_expr )
        elif not self.keyexpr.containsResultsKeywords():
            self.keyexpr.append( add_expr )

    def satisfies_keywords(self, keyword_list, include_results=True):
        ""
        if self.keyexpr:
            return self.keyexpr.evaluate( keyword_list.count, include_results )
        return True

    def setParameterExpression(self, param_expr):
        ""
        self.paramexpr = param_expr

    def evaluate_parameters(self, paramD):
        ""
        if self.paramexpr:
            return self.paramexpr.evaluate( paramD )
        else:
            return True

    def evaluate_option_expr(self, expr):
        """
        Evaluate the given expression against the list of command line options.
        """
        return expr.evaluate( self.optlist.count )

    def setRuntimeRange(self, min_runtime, max_runtime):
        ""
        self.runtime_range = [ min_runtime, max_runtime ]

    def evaluate_runtime(self, test_runtime):
        """
        If a runtime range is specified in this object, the given runtime is
        evaluated against that range.  False is returned only if the given
        runtime is outside the specified range.
        """
        if self.runtime_range:
            mn,mx = self.runtime_range
            if mn != None and test_runtime < mn:
                return False
            if mx != None and test_runtime > mx:
                return False

        return True

    def setRuntimeSum(self, time_sum):
        ""
        self.runtime_sum = time_sum

    def getRuntimeSum(self):
        ""
        return self.runtime_sum

    def setIncludeTDD(self, true_or_false):
        ""
        self.include_tdd = true_or_false

    def applyTDDExpression(self, true_or_false):
        ""
        self.apply_tdd = true_or_false

    def evaluate_TDD(self, test_keywords):
        ""
        if self.apply_tdd and not self.include_tdd:
            if 'TDD' in test_keywords:
                return False

        return True

    def setMaxSize(self, maxsize):
        ""
        self.maxsize = maxsize

    def applyMaxProcsExpression(self, true_or_false):
        ""
        self.apply_maxprocs = true_or_false

    def applyMaxDevicesExpression(self, true_or_false):
        ""
        self.apply_maxdevices = true_or_false

    def evaluate_maxprocs(self, test_size):
        ""
        if self.maxsize != None:

            maxnp,maxnd = self.maxsize
            np,nd = test_size

            if self.apply_maxprocs and np > maxnp:
                return False

        return True

    def evaluate_maxdevices(self, test_size):
        ""
        if self.maxsize != None:

            maxnp,maxnd = self.maxsize
            np,nd = test_size

            if self.apply_maxdevices and nd > maxnd:
                return False

        return True

    def setFileSearch(self, list_of_regex, list_of_file_globs):
        ""
        self.filesearch = FileSearcher( list_of_regex, list_of_file_globs )

    def evaluate_file_search(self, testfilename, name, params, files):
        ""
        if self.filesearch:
            return self.filesearch.search( testfilename, name, params, files )
        else:
            return True


class PlatformEvaluator:
    """
    Tests can use platform expressions to enable/disable the test.  This class
    caches the expressions and provides a function that answers the question

        "Would the test run on the given platform name?"
    """
    def __init__(self, list_of_word_expr):
        self.exprL = list_of_word_expr

    def satisfies_platform(self, plat_name):
        ""
        for wx in self.exprL:
            if not wx.evaluate( lambda tok: tok == plat_name ):
                return False
        return True


class FileSearcher:

    def __init__(self, regex_patterns, file_globs):
        ""
        self.regex = regex_patterns
        self.globs = file_globs

    def search(self, testfilename, name, params, files):
        """
        Searches certain test files that are linked or copied in the test for
        regular expression patterns.  Returns true if at least one pattern
        matched in one of the files.  Also returns true if no regular
        expressions were given at construction.
        """
        if self.regex == None or len(self.regex) == 0:
            return True

        if self.search_filename( testfilename ):
            return True

        if self.globs == None:
            # filter not applied if no file glob patterns
            return True

        varD = { 'NAME':name }
        for k,v in params.items():
            varD[k] = v

        xmldir = os.path.dirname( testfilename )
        for src,dest in files:
            src = expand_variables(src,varD)
            for fn in self.globs:
                if fnmatch.fnmatch( os.path.basename(src), fn ):
                    f = os.path.join( xmldir, src )
                    if os.path.isfile(f):
                        if self.search_filename( f ):
                            return True

        return False


    def search_filename(self, filename):
        ""
        try:
            with open(filename) as fp:
                content = fp.read()

        except Exception:
            pass

        else:
            for p in self.regex:
                try:
                    if p.search(content):
                        return True
                except Exception:
                    pass

        return False


curly_pat = re.compile( '[$][{][^}]*[}]' )
var_pat   = re.compile( '[$][a-zA-Z][a-zA-Z0-9_]*' )


def expand_variables(s, vardict):
    """
    Expands the given string with values from the dictionary.  It will
    expand ${NAME} and $NAME style variables.
    """
    if s:

        # first, substitute from dictionary argument

        if len(vardict) > 0:

            idx = 0
            while idx < len(s):
                m = curly_pat.search( s, idx )
                if m != None:
                    p = m.span()
                    varname = s[ p[0]+2 : p[1]-1 ]
                    if varname in vardict:
                        varval = vardict[varname]
                        s = s[:p[0]] + varval + s[p[1]:]
                        idx = p[0] + len(varval)
                    else:
                        idx = p[1]
                else:
                    break

            idx = 0
            while idx < len(s):
                m = var_pat.search( s, idx )
                if m != None:
                    p = m.span()
                    varname = s[ p[0]+1 : p[1] ]
                    if varname in vardict:
                        varval = vardict[varname]
                        s = s[:p[0]] + varval + s[p[1]:]
                        idx = p[0] + len(varval)
                    else:
                        idx = p[1]
                else:
                    break

        # then replace un-expanded variables with empty strings
        
        s = curly_pat.sub('', s)
        s = var_pat.sub('', s)

    return s
