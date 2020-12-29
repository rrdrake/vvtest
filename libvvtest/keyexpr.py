#!/usr/bin/env python

# Copyright 2018 National Technology & Engineering Solutions of Sandia, LLC
# (NTESS). Under the terms of Contract DE-NA0003525 with NTESS, the U.S.
# Government retains certain rights in this software.


from .wordexpr import WordExpression
from .wordexpr import separate_expression_into_tokens
from .wordexpr import clean_up_word_expression
from .wordexpr import join_expressions_with_AND
from .wordexpr import TokenTree, prune_token_tree, collect_token_list_from_tree

from .teststatus import RESULTS_KEYWORDS
RESULTS_KEYWORD_SET = set( RESULTS_KEYWORDS )


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


class KeywordExpression:

    def __init__(self, expr=None):
        ""
        self.full = WordExpression( expr )
        nrexpr = make_non_results_expression( expr )
        self.non_results = WordExpression( nrexpr )

    def appendKeywordExpression(self, expr):
        """
        If a current expression exists containing results keywords (such as
        "diff" or "notdone"), then do nothing. Otherwise, AND the new
        expression to the existing.
        """
        if not self.containsResultsKeywords():
            self.full.append( expr )
            nrexpr = make_non_results_expression( self.full.getExpression() )
            self.non_results = WordExpression( nrexpr )

    def evaluate(self, keyword_list, include_results=True):
        ""
        if include_results:
            return self.full.evaluate( keyword_list )
        else:
            return self.non_results.evaluate( keyword_list )

    def containsResultsKeywords(self):
        ""
        fullwords = set( self.full.getWordList() )
        return len( RESULTS_KEYWORD_SET.intersection( fullwords ) ) > 0


def make_non_results_expression( expr ):
    ""
    if expr is None:
        return None

    toklist = separate_expression_into_tokens( expr )

    tree = TokenTree()
    tree.parse( toklist, 0 )

    while apply_pruning_operations( tree ) > 0:
        pass

    toks = []
    collect_token_list_from_tree( tree, toks )

    if len( toks ) == 0:
        return None
    else:
        return ' '.join( toks )


def is_results_token( tok ):
    ""
    return tok in RESULTS_KEYWORD_SET


def is_empty_subtree( tok ):
    ""
    return isinstance( tok, TokenTree ) and tok.numTokens() == 0


def apply_pruning_operations( tree ):
    ""
    cnt =  prune_token_tree( tree, is_results_token )
    cnt += prune_token_tree( tree, is_empty_subtree )
    return cnt
