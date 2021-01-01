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

    def evaluate(self, expr):
        ""
        pev = PlatformEvaluator( expr )
        return WordExpression._evaluate( self, pev.satisfies_platform )


class PlatformEvaluator:
    """
    Tests can use platform expressions to enable/disable the test.  This class
    caches the expressions and provides a function that answers the question

        "Would the test run on the given platform name?"
    """
    def __init__(self, word_expr):
        self.expr = word_expr

    def satisfies_platform(self, plat_name):
        ""
        if self.expr is not None:
            if not self.expr.evaluate( plat_name ):
                return False
        return True
