#!/usr/bin/env python

# Copyright 2018 National Technology & Engineering Solutions of Sandia, LLC
# (NTESS). Under the terms of Contract DE-NA0003525 with NTESS, the U.S.
# Government retains certain rights in this software.


from .teststatus import RESULTS_KEYWORDS
from .wordexpr import WordExpression
from .wordexpr import convert_token_list_into_eval_string
from .wordexpr import separate_expression_into_tokens
from .wordexpr import add_words_to_set
from .wordexpr import _OPERATOR_LIST
from .wordexpr import clean_up_word_expression
from .wordexpr import join_expressions_with_AND


class KeywordExpression( WordExpression ):

    def evaluate(self, keyword_list):
        ""
        return WordExpression.evaluate( self, keyword_list )


class NonResultsKeywordExpression( KeywordExpression ):

    def _create_eval_expression(self, string_expr, wordset):
        ""
        return parse_non_results_expression( string_expr, wordset )

    def containsResultsKeywords(self):
        ""
        return len( set( RESULTS_KEYWORDS ).intersection( self.words ) ) > 0


def create_keyword_expression( word_expr_list, not_word_expr_list ):
    ""
    exprL = []

    if word_expr_list:
        for expr in word_expr_list:
            exprL.append( clean_up_word_expression(expr) )

    if not_word_expr_list:
        for expr in not_word_expr_list:
            exprL.append( clean_up_word_expression( expr, negate=True ) )

    if len( exprL ) > 0:
        return KeywordExpression( join_expressions_with_AND( exprL ) )

    return None


def parse_non_results_expression( expr, wordset=None ):
    ""
    nrmod = NonResultsExpressionModifier( expr, wordset )
    toklist = nrmod.getNonResultsTokenList()

    if len( toklist ) == 0:
        return None
    else:
        evalexpr = convert_token_list_into_eval_string( toklist )
        return evalexpr


class NonResultsExpressionModifier:

    def __init__(self, expr, wordset):
        ""
        self.toklist = separate_expression_into_tokens( expr )
        add_words_to_set( self.toklist, wordset )

        self.toki = 0

        self.nonresults_toklist = self.parse_subexpr()

        trim_leading_binary_operator( self.nonresults_toklist )

    def getNonResultsTokenList(self):
        ""
        return self.nonresults_toklist

    def parse_subexpr(self):
        ""
        toklist = []
        oplist = []

        while self.toki < len( self.toklist ):

            tok = self.toklist[ self.toki ]
            self.toki += 1

            if tok in _OPERATOR_LIST:
                if tok == ')':
                    break
                elif tok == '(':
                    sublist = self.parse_subexpr()
                    if sublist:
                        append_sublist( toklist, oplist, sublist )
                    oplist = []
                else:
                    oplist.append( tok )

            elif tok in RESULTS_KEYWORDS:
                oplist = []

            else:
                append_token( toklist, oplist, tok )
                oplist = []

        return toklist


def trim_leading_binary_operator( toklist ):
    ""
    if toklist:
        if toklist[0] == 'and' or toklist[0] == 'or':
            toklist.pop( 0 )


def append_sublist( toklist, oplist, sublist ):
    ""
    append_operator( toklist, oplist )

    if oplist and len( sublist ) > 1:
        sublist = ['(']+sublist+[')']

    toklist.extend( sublist )


def append_token( toklist, oplist, tok ):
    ""
    append_operator( toklist, oplist )
    toklist.append( tok )


def append_operator( toklist, oplist ):
    ""
    if oplist:
        toklist.extend( oplist )
