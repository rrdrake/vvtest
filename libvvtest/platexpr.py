#!/usr/bin/env python

# Copyright 2018 National Technology & Engineering Solutions of Sandia, LLC
# (NTESS). Under the terms of Contract DE-NA0003525 with NTESS, the U.S.
# Government retains certain rights in this software.

from .wordexpr import WordExpression
from .wordexpr import clean_up_word_expression
from .wordexpr import join_expressions_with_AND


def create_platform_expression( word_expr_list, not_word_expr_list ):
    ""
    exprL = []

    if word_expr_list:
        for expr in word_expr_list:
            exprL.append( clean_up_word_expression(expr) )

    if not_word_expr_list:
        for expr in not_word_expr_list:
            exprL.append( clean_up_word_expression( expr, negate=True ) )

    if len( exprL ) > 0:
        return PlatformExpression( join_expressions_with_AND( exprL ) )

    return None


class PlatformExpression( WordExpression ):

    def __init__(self, expr=None):
        """
        The 'expr' here is a (string) expression coming from the command line.
        """
        WordExpression.__init__( self, expr )

    def evaluate(self, word_expr):
        """
        The 'word_expr' here is a WordExpression coming from the test file.
        """
        pev = PlatformEvaluator( word_expr )
        return WordExpression._evaluate( self, pev.satisfies_platform,
                                         case_insensitive=True )


class PlatformEvaluator:
    """
    Tests can use platform expressions to enable/disable the test.  This class
    caches the expressions and provides a function that answers the question

        Would the test run on the given platform name?
    """
    def __init__(self, word_expr):
        self.expr = word_expr

    def satisfies_platform(self, plat_name):
        ""
        if self.expr is not None:
            if not self.expr.evaluate( plat_name.lower(),
                                       case_insensitive=True ):
                return False
        return True
