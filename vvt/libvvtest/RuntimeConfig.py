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

    known_attrs = [ \
       'param_expr_list',   # k-format or string expression parameter filter
       'keyword_expr',      # a WordExpression object for keyword filtering
       'option_list',       # list of build options
       'include_all',       # boolean to turn off test inclusion filtering
       'runtime_range',     # [ minimum runtime, maximum runtime ]
       'runtime_sum',       # maximum accumulated runtime
    ]

    defaults = { \
        'vvtestdir'  : None,  # the top level vvtest directory
        'configdir'  : [],    # the configuration directory(ies)
        'exepath'    : None,  # the path to the executables
        'onopts'     : [],
        'offopts'    : [],
        'refresh'    : 1,
        'postclean'  : 0,
        'timeout'    : None,
        'multiplier' : 1.0,
        'preclean'   : 1,
        'analyze'    : 0,
        'logfile'    : 1,
        'testargs'   : [],
    }

    def __init__(self, **kwargs ):
        ""
        self.attrs = {}

        self.platname = None
        self.platexpr = None
        self.apply_platexpr = True

        self.maxprocs = None
        self.apply_maxprocs = True

        self.include_tdd = False
        self.apply_tdd = True

        self.filesearch = None

        for n,v in RuntimeConfig.defaults.items():
            self.setAttr( n, v )

        for k,v in kwargs.items():
            self.setAttr( k, v )

    def setAttr(self, name, value):
        """
        Set the value of an attribute name (which must be known).
        """
        self.attrs[name] = value

        if name == 'param_expr_list':
            self.attrs['param_filter'] = FilterExpressions.ParamFilter( value )

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

    def getPlatformName(self):
        ""
        return self.platname

    def setPlatformExpression(self, expr):
        ""
        self.platexpr = expr

    def getPlatformExpression(self):
        ""
        return self.platexpr

    def applyPlatformExpression(self, true_or_false):
        ""
        self.apply_platexpr = true_or_false

    def evaluate_platform_include(self, list_of_platform_expr):
        ""
        ok = True

        if self.apply_platexpr:

            pname = self.getPlatformName()
            pexpr = self.getPlatformExpression()
            if pexpr != None:
                platexpr = pexpr
            else:
                # the current platform is used as the expression
                platexpr = FilterExpressions.WordExpression( pname )

            # to evaluate the command line expression, each platform name in the
            # expression is evaluated using PlatformEvaluator.satisfies_platform()
            pev = PlatformEvaluator( list_of_platform_expr )
            ok = platexpr.evaluate( pev.satisfies_platform )

        return ok

    def getOptionList(self):
        ""
        return self.attrs.get( 'option_list', [] )

    def addResultsKeywordExpression(self, add_expr):
        ""
        expr = self.attrs['keyword_expr']
        if not expr.containsResultsKeywords():
            expr.append( add_expr, 'and' )

    def satisfies_keywords(self, keyword_list, include_results=True):
        ""
        if 'keyword_expr' in self.attrs:
            expr = self.attrs['keyword_expr']
            return expr.evaluate( keyword_list.count, include_results )
        return True

    def evaluate_parameters(self, paramD):
        ""
        pf = self.attrs.get( 'param_filter', None )
        if pf == None: return 1
        return pf.evaluate(paramD)

    def evaluate_option_expr(self, expr):
        """
        Evaluate the given expression against the list of command line options.
        """
        opL = self.attrs.get( 'option_list', [] )
        return expr.evaluate( opL.count )

    def evaluate_runtime(self, test_runtime):
        """
        If a runtime range is specified in this object, the given runtime is
        evaluated against that range.  False is returned only if the given
        runtime is outside the specified range.
        """
        mn,mx = self.attrs.get( 'runtime_range', [None,None] )
        if mn != None and test_runtime < mn:
            return False
        if mx != None and test_runtime > mx:
            return False

        return True

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

    def setMaxProcs(self, numprocs):
        ""
        self.maxprocs = numprocs

    def applyMaxProcsExpression(self, true_or_false):
        ""
        self.apply_maxprocs = true_or_false

    def evaluate_maxprocs(self, test_np):
        ""
        if self.apply_maxprocs:
            if self.maxprocs != None and test_np > self.maxprocs:
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
